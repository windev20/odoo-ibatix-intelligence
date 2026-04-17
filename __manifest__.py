{
    'name': 'IBATIX Intelligence',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Socle d\'intelligence logicielle IBATIX — calcul automatique des primes CEE et MaPrimeRénov\'',
    'author': 'ibatix',
    'depends': [
        'mail',
        'objets_ibatix',
        'ibatix_champs',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
