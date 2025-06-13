# Generated by Django 5.1 on 2024-08-15 14:49

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("servers", "0001_initial"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="containerimage",
            index=models.Index(fields=["image"], name="servers_con_image_108589_idx"),
        ),
        migrations.AddIndex(
            model_name="containerimage",
            index=models.Index(
                fields=["imageid"], name="servers_con_imageid_443ff6_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="host",
            index=models.Index(
                fields=["hostname"], name="servers_hos_hostnam_3817b8_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="hostdetails",
            index=models.Index(fields=["domain"], name="servers_hos_domain_1cd62e_idx"),
        ),
        migrations.AddIndex(
            model_name="hostdetails",
            index=models.Index(
                fields=["osname", "osrelease"], name="servers_hos_osname_444966_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="hostdetails",
            index=models.Index(fields=["ipv4"], name="servers_hos_ipv4_b4e758_idx"),
        ),
        migrations.AddIndex(
            model_name="hostdetails",
            index=models.Index(fields=["ipv6"], name="servers_hos_ipv6_ea493c_idx"),
        ),
        migrations.AddIndex(
            model_name="hostdetails",
            index=models.Index(
                fields=["fail2ban"], name="servers_hos_fail2ba_69bc45_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="package",
            index=models.Index(fields=["name"], name="servers_pac_name_555898_idx"),
        ),
        migrations.AddIndex(
            model_name="package",
            index=models.Index(
                fields=["name", "version"], name="servers_pac_name_ccdde8_idx"
            ),
        ),
    ]
