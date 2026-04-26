from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_subject_class_id'),
    ]

    operations = [
        # 1. Crée la table Teacher
        migrations.CreateModel(
            name='Teacher',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('full_name', models.CharField(max_length=255)),
                ('email', models.EmailField(blank=True, null=True)),
                ('department', models.CharField(blank=True, max_length=255, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={'ordering': ['full_name']},
        ),
        # 2. Supprime l'ancien M2M teachers (Profile)
        migrations.RemoveField(model_name='document', name='teachers'),
        # 3. Ajoute le nouveau M2M teachers (Teacher)
        migrations.AddField(
            model_name='document',
            name='teachers',
            field=models.ManyToManyField(blank=True, related_name='documents', to='core.teacher'),
        ),
    ]
