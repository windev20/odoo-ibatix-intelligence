from odoo import api, models

# Plafonds de ressources MPR 2026 — Source : Guide des aides financières ANAH, édition février 2026
# Colonnes : (très_modeste, modeste, intermédiaire)
THRESHOLDS_2026 = {
    'idf': {
        1: (24031, 29253, 40851),
        2: (35270, 42933, 60051),
        3: (42357, 51564, 71846),
        4: (49455, 60208, 84562),
        5: (56580, 68877, 96817),
        'increment': (7116, 8663, 12257),
    },
    'hors_idf': {
        1: (17363, 22259, 31185),
        2: (25393, 32553, 45842),
        3: (30540, 39148, 55196),
        4: (35676, 45735, 64550),
        5: (40835, 52348, 73907),
        'increment': (5151, 6598, 9357),
    },
}

IDF_DEPARTMENTS = {'75', '77', '78', '91', '92', '93', '94', '95'}


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_zone(self, zip_code):
        """Détermine la zone géographique (idf / hors_idf) à partir du code postal."""
        if not zip_code or len(zip_code) < 2:
            return 'hors_idf'
        dept = zip_code[:2]
        return 'idf' if dept in IDF_DEPARTMENTS else 'hors_idf'

    def _get_thresholds(self, zone, nb_personnes):
        """Retourne les plafonds (très modeste, modeste, intermédiaire) pour la zone et le foyer."""
        table = THRESHOLDS_2026[zone]
        nb = max(1, nb_personnes)
        if nb <= 5:
            t = table[nb]
        else:
            base = table[5]
            inc = table['increment']
            extra = nb - 5
            t = (
                base[0] + extra * inc[0],
                base[1] + extra * inc[1],
                base[2] + extra * inc[2],
            )
        return t  # (très_modeste, modeste, intermédiaire)

    def action_compute_precarite(self):
        """Calcule automatiquement la catégorie MPR du client selon ses revenus fiscaux et sa zone."""
        for partner in self:
            if not partner.fiscal_ids:
                continue

            # 1. Année fiscale la plus récente
            max_year = max(partner.fiscal_ids.mapped('annee_fiscale') or [0])
            if not max_year:
                continue
            recent = partner.fiscal_ids.filtered(lambda r: r.annee_fiscale == max_year)

            # 2. Somme des revenus et des parts pour cette année
            total_revenue = sum(recent.mapped('revenu_fiscal'))
            total_parts = sum(recent.mapped('nb_parts_foyer'))
            nb_personnes = max(1, total_parts)

            # 3. Zone géographique via le code postal
            zone = self._get_zone(partner.zip or '')

            # 4. Plafonds correspondants
            tres_modeste, modeste, intermediaire = self._get_thresholds(zone, nb_personnes)

            # 5. Catégorie MPR
            if total_revenue <= tres_modeste:
                categorie = 'bleu'       # 🔵 Très modeste
            elif total_revenue <= modeste:
                categorie = 'jaune'      # 🟡 Modeste
            elif total_revenue <= intermediaire:
                categorie = 'violet'     # 🟣 Intermédiaire
            else:
                categorie = 'rose'       # 🩷 Supérieur

            partner.categorie_mpr = categorie

            # 6. Catégorie CEE (déduite de la catégorie MPR)
            mpr_to_cee = {
                'bleu': 'precaire',
                'jaune': 'modeste',
                'violet': 'classique',
                'rose': 'classique',
            }
            partner.categorie_precarite = mpr_to_cee.get(categorie, False)
