import base64
import io
import json
import logging

from odoo import models

_logger = logging.getLogger(__name__)


def _extract_with_claude(pdf_bytes, api_key):
    """
    Envoie le PDF a l'API Claude et retourne un dict avec les champs fiscaux.
    Utilise le modele claude-haiku-4-5-20251001 (rapide et economique).
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
                            "situation declarative) et extrais exactement ces informations en JSON:\n"
                            "{\n"
                            '  "numero_fiscal": "les 13 chiffres du numero fiscal SPI (sans espaces)",\n'
                            '  "reference_fiscal": "la reference du document telle quelle",\n'
                            '  "annee_fiscale": 2022,\n'
                            '  "revenu_fiscal": 95102,\n'
                            '  "nb_parts_foyer": 1\n'
                            "}\n"
                            "Regles:\n"
                            "- numero_fiscal: uniquement les 13 chiffres, sans espaces ni parentheses\n"
                            "- reference_fiscal: la chaine complete telle qu'elle apparait (ex: '23 B5 8859482 47')\n"
                            "- annee_fiscale: l'annee des revenus concernes (entier)\n"
                            "- revenu_fiscal: le revenu fiscal de reference en euros (entier, sans espaces)\n"
                            "- nb_parts_foyer: le nombre de parts du foyer fiscal (entier arrondi)\n"
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

    return result


class IbatixPartnerFiscal(models.Model):
    _inherit = 'ibatix.partner.fiscal'

    def action_parse_avis_imposition(self):
        """Analyse le PDF de l'avis d'imposition et remplit les champs fiscaux via Claude API."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('ibatix.anthropic_api_key', '')

        for record in self:
            if not record.avis_imposition:
                continue
            try:
                pdf_bytes = base64.b64decode(record.avis_imposition)
            except Exception as e:
                _logger.warning("Impossible de decoder le fichier pour la ligne %s : %s", record.id, e)
                continue

            if not api_key:
                _logger.warning(
                    "Cle API Anthropic non configuree. "
                    "Ajoutez le parametre 'ibatix.anthropic_api_key' dans Parametres > Technique > Parametres systeme."
                )
                record.env.user.notify_warning(
                    message="Clé API Anthropic manquante. Configurez le paramètre 'ibatix.anthropic_api_key'.",
                    title="Analyse impossible",
                    sticky=True,
                ) if hasattr(record.env.user, 'notify_warning') else None
                continue

            data = _extract_with_claude(pdf_bytes, api_key)
            if data:
                record.write(data)
                _logger.info("Avis d'imposition analyse pour la ligne %s : %s", record.id, data)
            else:
                _logger.warning("Aucun champ extrait du PDF pour la ligne %s", record.id)
