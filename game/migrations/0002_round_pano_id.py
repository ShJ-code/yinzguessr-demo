# Switch rounds from Mapillary images to Google Street View panoramas.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(model_name="round", name="image_id"),
        migrations.RemoveField(model_name="round", name="is_pano"),
        migrations.RemoveField(model_name="round", name="lat"),
        migrations.RemoveField(model_name="round", name="lng"),
        migrations.AddField(
            model_name="round",
            name="pano_id",
            field=models.CharField(default="", max_length=128),
            preserve_default=False,
        ),
    ]
