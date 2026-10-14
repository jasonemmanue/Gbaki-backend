"""
Harmonise les classes ENSEA : codes sans espace (ISE 1 -> ISE1), libellés « AS 2 »,
cycle « Ingénieur » avec majuscule, ordre AS 1 -> ISE 3. Les liens (profils,
matières, documents) passent par l'id : rien d'autre ne change.
"""
from django.db import migrations

CLASSES = {
    # code : (libellé, cycle, ordre)
    'AS1':  ('AS 1',  'Licence',   1),
    'AS2':  ('AS 2',  'Licence',   2),
    'AS3':  ('AS 3',  'Licence',   3),
    'IPS1': ('IPS 1', 'Master',    4),
    'IPS2': ('IPS 2', 'Master',    5),
    'ISE1': ('ISE 1', 'Ingénieur', 6),
    'ISE2': ('ISE 2', 'Ingénieur', 7),
    'ISE3': ('ISE 3', 'Ingénieur', 8),
}


def harmonise(apps, schema_editor):
    Class = apps.get_model('core', 'Class')
    taken = {c.code for c in Class.objects.all()}
    for c in Class.objects.all():
        code = c.code.replace(' ', '').upper()
        if code not in CLASSES:
            continue
        if code != c.code and code in taken:
            continue   # une classe porte déjà ce code : on ne crée pas de doublon
        c.code = code
        c.label, c.cycle, c.level_order = CLASSES[code]
        c.save(update_fields=['code', 'label', 'cycle', 'level_order'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_otpcode_attempts'),
    ]

    operations = [
        migrations.RunPython(harmonise, migrations.RunPython.noop),
    ]
