import base64
import io
import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)


def _extract_pdf_text(pdf_bytes):
    """Extrait le texte brut d'un PDF via PyPDF2."""
    try:
        from PyPDF2 import PdfReader  # noqa: PLC0415
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or '')
        return '\n'.join(pages)
    except Exception as e:
        _logger.warning("Echec extraction PDF : %s", e)
        return ''


def _clean_number(raw):
    """Supprime les espaces insecables et espaces dans une chaine numerique."""
    return re.sub(r'[\s\u00a0\u202f]+', '', raw)


def _parse_avis_imposition(text):
    """
    Analyse le texte extrait d'un avis d'imposition francais et retourne
    un dict avec les champs reconnus.
    """
    result = {}

    # ── 1. Numero fiscal (SPI) ── 13 chiffres, eventuellement espaces
    m = re.search(
        r"num[ée]ro\s+fiscal[^0-9]{0,30}(\d[\d\s\u00a0\u202f]{10,18}\d)",
        text, re.IGNORECASE
    )
    if m:
        raw = _clean_number(m.group(1))
        if len(raw) == 13:
            result['numero_fiscal'] = raw

    # ── 2. Reference de l'avis (ou reference fiscale)
    m = re.search(
        r"r[ée]f[ée]rence\s+(?:de\s+l.avis|fiscal)[^0-9]{0,30}(\d[\d\s\u00a0\u202f]{6,25}\d)",
        text, re.IGNORECASE
    )
    if m:
        raw = _clean_number(m.group(1))
        result['reference_fiscal'] = raw

    # ── 3. Annee fiscale
    # Priorite : "revenus de l'annee XXXX" ou "revenus XXXX"
    m = re.search(
        r"revenus?\s+(?:de\s+l.ann[ée]e\s+|de\s+)?(\d{4})",
        text, re.IGNORECASE
    )
    if not m:
        m = re.search(
            r"(?:avis\s+d.imposition|ann[ée]e\s+d.imposition)[^0-9]{0,20}(\d{4})",
            text, re.IGNORECASE
        )
    if not m:
        m = re.search(r'\b(20\d{2})\b', text)
    if m:
        result['annee_fiscale'] = int(m.group(1))

    # ── 4. Revenu fiscal de reference (montant entier en euros)
    m = re.search(
        r"revenu\s+fiscal\s+de\s+r[ée]f[ée]rence[^0-9]{0,50}(\d[\d\s\u00a0\u202f]*\d|\d)",
        text, re.IGNORECASE
    )
    if m:
        raw = _clean_number(m.group(1))
        try:
            result['revenu_fiscal'] = float(raw)
        except ValueError:
            pass

    # ── 5. Nombre de parts du foyer fiscal
    m = re.search(
        r"nombre\s+de\s+parts?[^0-9]{0,30}(\d+(?:[,.]\d+)?)",
        text, re.IGNORECASE
    )
    if m:
        raw = m.group(1).replace(',', '.')
        try:
            result['nb_parts_foyer'] = round(float(raw))
        except ValueError:
            pass

    return result


class IbatixPartnerFiscal(models.Model):
    _inherit = 'ibatix.partner.fiscal'

    def action_parse_avis_imposition(self):
        """Analyse le PDF de l'avis d'imposition et remplit les champs fiscaux."""
        for record in self:
            if not record.avis_imposition:
                continue
            try:
                pdf_bytes = base64.b64decode(record.avis_imposition)
            except Exception as e:
                _logger.warning("Impossible de decoder le fichier pour la ligne %s : %s", record.id, e)
                continue

            text = _extract_pdf_text(pdf_bytes)
            if not text.strip():
                _logger.warning("Aucun texte extrait du PDF pour la ligne %s", record.id)
                continue

            data = _parse_avis_imposition(text)
            if data:
                record.write(data)
                _logger.info("Avis d'imposition analyse pour la ligne %s : %s", record.id, data)
            else:
                _logger.warning("Aucun champ reconnu dans le PDF pour la ligne %s", record.id)
