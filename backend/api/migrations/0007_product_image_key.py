import base64
import binascii
import logging

from django.db import migrations, models

logger = logging.getLogger(__name__)


def move_inline_images_to_files(apps, schema_editor):
    """Convert base64 data URLs stored on products into WebP files. Rows already converted are skipped."""
    from api import images

    Product = apps.get_model("api", "Product")
    for product in Product.objects.exclude(image="").filter(image_key="").iterator():
        _, _, payload = product.image.partition(",")
        try:
            raw = base64.b64decode(payload, validate=True)
            key = images.save(images.render(raw))
        except (binascii.Error, ValueError):
            logger.warning("Product %s has an unreadable inline image; dropping it.", product.pk)
            continue
        Product.objects.filter(pk=product.pk).update(image_key=key, image="")


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='image_key',
            field=models.CharField(blank=True, default='', max_length=32),
        ),
        migrations.RunPython(move_inline_images_to_files, migrations.RunPython.noop),
    ]
