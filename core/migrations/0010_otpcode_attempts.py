from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_fulltext_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='otpcode',
            name='attempts',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='otpcode',
            name='purpose',
            field=models.CharField(default='reset', max_length=10),
        ),
        # Les comptes existants n'ont jamais prouvé leur adresse : vérification à la prochaine connexion
        migrations.AddField(
            model_name='profile',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
    ]
