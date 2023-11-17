FROM odoo:17

USER root

RUN pip3 install --no-cache-dir Pyjwt && \
    echo "list_db = False" >> /etc/odoo/odoo.conf

USER odoo

COPY autologin /mnt/extra-addons/autologin
COPY frepple /mnt/extra-addons/frepple
COPY freppledata /mnt/extra-addons/freppledata