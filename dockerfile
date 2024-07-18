FROM odoo:17

USER root

# Comment the next line to run in multi-database mode
RUN echo "list_db = False" >> /etc/odoo/odoo.conf

RUN echo "limit_time_cpu = 600" >> /etc/odoo/odoo.conf && \
    echo "limit_time_real = 600" >> /etc/odoo/odoo.conf

USER odoo

COPY autologin /mnt/extra-addons/autologin
COPY frepple /mnt/extra-addons/frepple
COPY freppledata /mnt/extra-addons/freppledata