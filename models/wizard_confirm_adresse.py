from odoo import fields, models


class WizardConfirmAdresse(models.TransientModel):
    _name = 'ibatix.wizard.confirm.adresse'
    _description = "Confirmation de l'adresse extraite de l'avis d'imposition"

    partner_id = fields.Many2one('res.partner', required=True, readonly=True)

    # Donnees extraites du document
    nom_extrait = fields.Char(string="Nom extrait", readonly=True)
    street_extrait = fields.Char(string="Rue", readonly=True)
    street2_extrait = fields.Char(string="Complement", readonly=True)
    zip_extrait = fields.Char(string="Code postal", readonly=True)
    city_extrait = fields.Char(string="Ville", readonly=True)

    def action_oui(self):
        """Confirme : met a jour le nom ET l'adresse du partenaire."""
        vals = {}
        if self.nom_extrait:
            vals['name'] = self.nom_extrait
        if self.street_extrait:
            vals['street'] = self.street_extrait
        if self.street2_extrait:
            vals['street2'] = self.street2_extrait
        if self.zip_extrait:
            vals['zip'] = self.zip_extrait
        if self.city_extrait:
            vals['city'] = self.city_extrait
        if vals:
            self.partner_id.sudo().write(vals)
        return {'type': 'ir.actions.act_window_close'}

    def action_non(self):
        """Refuse l'adresse : met a jour uniquement le nom du partenaire."""
        if self.nom_extrait:
            self.partner_id.sudo().write({'name': self.nom_extrait})
        return {'type': 'ir.actions.act_window_close'}
