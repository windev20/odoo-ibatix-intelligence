import base64
import io
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


def _extract_with_claude(pdf_bytes, api_key):
    """
    Envoie le PDF a l'API Claude et retourne un dict avec les champs fiscaux
    et les informations d'identite / adresse du contribuable.
    """
    import urllib.request
    import urllib.error

    pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')

    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 512,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "Analyse ce document fiscal francais (avis d'imposition ou avis de "
                            "situation declarative) et extrais exactement ces informations en JSON :\n"
                            "{\n"
                            '  "numero_fiscal": "les 13 chiffres du numero fiscal SPI (sans espaces)",\n'
                            '  "reference_fiscal": "la reference du document telle quelle (ex: 23 B5 8859482 47)",\n'
                            '  "annee_fiscale": 2022,\n'
                            '  "revenu_fiscal": 95102,\n'
                            '  "nb_parts_foyer": 1,\n'
                            '  "nom_client": "Prenom NOM du contribuable, capitalise normalement (ex: Joseph ABITBOL)",\n'
                            '  "street": "numero et nom de la rue (ex: 19 Rue du Fosse des Treize)",\n'
                            '  "street2": "complement d\'adresse si present, sinon null (ex: Bat. B, App. 12)",\n'
                            '  "zip": "code postal a 5 chiffres (ex: 67000)",\n'
                            '  "city": "ville (ex: Strasbourg)"\n'
                            "}\n"
                            "Regles :\n"
                            "- numero_fiscal : uniquement les 13 chiffres, sans espaces\n"
                            "- reference_fiscal : la chaine complete telle qu'elle apparait\n"
                            "- annee_fiscale : l'annee des revenus concernes (entier)\n"
                            "- revenu_fiscal : le revenu fiscal de reference en euros (entier, sans espaces)\n"
                            "- nb_parts_foyer : le nombre de parts du foyer fiscal (entier arrondi)\n"
                            "- nom_client : capitaliser correctement (Prenom NOM), ne pas mettre tout en majuscules\n"
                            "- street : uniquement la ligne principale de l'adresse (numero + voie)\n"
                            "- street2 : batiment, appartement, etage, etc. (null si absent)\n"
                            "Si un champ est absent du document, mets null.\n"
                            "Reponds UNIQUEMENT avec le JSON, sans aucun texte supplementaire."
                        ),
                    },
                ],
            }
        ],
    }

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        'https://api.anthropic.com/v1/messages',
        data=data,
        headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'pdfs-2024-09-25',
            'content-type': 'application/json',
        },
        method='POST',
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        _logger.error("Claude API erreur %s : %s", e.code, error_body)
        return {}

    raw_text = body.get('content', [{}])[0].get('text', '').strip()
    _logger.info("Reponse Claude : %s", raw_text)

    # Nettoyer les eventuels blocs markdown ```json ... ```
    if raw_text.startswith('```'):
        lines = raw_text.splitlines()
        raw_text = '\n'.join(lines[1:-1] if lines[-1] == '```' else lines[1:])

    try:
        extracted = json.loads(raw_text)
    except json.JSONDecodeError as e:
        _logger.error("Impossible de parser le JSON Claude : %s — %s", e, raw_text)
        return {}

    result = {}

    # Champs fiscaux
    if extracted.get('numero_fiscal'):
        result['numero_fiscal'] = str(extracted['numero_fiscal'])
    if extracted.get('reference_fiscal'):
        result['reference_fiscal'] = str(extracted['reference_fiscal'])
    if extracted.get('annee_fiscale') is not None:
        try:
            result['annee_fiscale'] = int(extracted['annee_fiscale'])
        except (ValueError, TypeError):
            pass
    if extracted.get('revenu_fiscal') is not None:
        try:
            result['revenu_fiscal'] = float(extracted['revenu_fiscal'])
        except (ValueError, TypeError):
            pass
    if extracted.get('nb_parts_foyer') is not None:
        try:
            result['nb_parts_foyer'] = round(float(extracted['nb_parts_foyer']))
        except (ValueError, TypeError):
            pass

    # Identite et adresse (stockees separement pour le wizard)
    for key in ('nom_client', 'street', 'street2', 'zip', 'city'):
        val = extracted.get(key)
        if val:
            result[key] = str(val)

    return result


class IbatixPartnerFiscal(models.Model):
    _inherit = 'ibatix.partner.fiscal'

    def action_parse_avis_imposition(self):
        """
        Analyse le PDF via Claude API, remplit les champs fiscaux,
        puis ouvre un wizard de confirmation pour le nom et l'adresse.
        """
        api_key = self.env['ir.config_parameter'].sudo().get_param('ibatix.anthropic_api_key', '')

        if not api_key:
            _logger.warning(
                "Cle API Anthropic non configuree. "
                "Ajoutez 'ibatix.anthropic_api_key' dans Parametres > Technique > Parametres systeme."
            )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Clé API manquante",
                    'message': "Configurez le paramètre 'ibatix.anthropic_api_key' dans Paramètres > Technique > Paramètres système.",
                    'type': 'warning',
                    'sticky': True,
                },
            }

        # On traite le premier enregistrement (appel depuis le bouton de ligne)
        record = self[0]

        if not record.avis_imposition:
            return

        try:
            pdf_bytes = base64.b64decode(record.avis_imposition)
        except Exception as e:
            _logger.warning("Impossible de decoder le fichier pour la ligne %s : %s", record.id, e)
            return

        data = _extract_with_claude(pdf_bytes, api_key)
        if not data:
            _logger.warning("Aucun champ extrait du PDF pour la ligne %s", record.id)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Analyse échouée",
                    'message': "Impossible d'extraire les données du document. Vérifiez les logs.",
                    'type': 'danger',
                    'sticky': False,
                },
            }

        # 1. Écrire les champs fiscaux sur la ligne
        fiscal_keys = {'numero_fiscal', 'reference_fiscal', 'annee_fiscale', 'revenu_fiscal', 'nb_parts_foyer'}
        fiscal_data = {k: v for k, v in data.items() if k in fiscal_keys}
        if fiscal_data:
            record.write(fiscal_data)
            _logger.info("Donnees fiscales mises a jour pour la ligne %s : %s", record.id, fiscal_data)

        # 2. Ouvrir le wizard si nom ou adresse ont ete extraits
        identity_keys = {'nom_client', 'street', 'street2', 'zip', 'city'}
        identity_data = {k: v for k, v in data.items() if k in identity_keys}

        if not identity_data:
            # Pas d'identite extraite, on s'arrête là
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': "Analyse terminée",
                    'message': "Données fiscales mises à jour. Aucune identité trouvée dans le document.",
                    'type': 'success',
                    'sticky': False,
                },
            }

        wizard = self.env['ibatix.wizard.confirm.adresse'].create({
            'partner_id': record.partner_id.id,
            'nom_extrait': identity_data.get('nom_client', ''),
            'street_extrait': identity_data.get('street', ''),
            'street2_extrait': identity_data.get('street2', ''),
            'zip_extrait': identity_data.get('zip', ''),
            'city_extrait': identity_data.get('city', ''),
        })

        return {
            'type': 'ir.actions.act_window',
            'name': "Mise à jour de la fiche client",
            'res_model': 'ibatix.wizard.confirm.adresse',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
