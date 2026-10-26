FROM odoo:20

USER root

ARG MULTIDB
ARG PROXYMODE

RUN if [[ "x$MULTIDB" == "x" ]] ; then  echo "list_db = False" >> /etc/odoo/odoo.conf ; fi

RUN if [[ "x$PROXYMODE" != "x" ]] ; then  echo "proxy_mode = True" >> /etc/odoo/odoo.conf ; fi

RUN echo "limit_time_cpu = 600" >> /etc/odoo/odoo.conf && \
    echo "limit_time_real = 600" >> /etc/odoo/odoo.conf && \
    echo "without_demo = False" >> /etc/odoo/odoo.conf

USER odoo

COPY autologin /mnt/extra-addons/autologin
COPY frepple /mnt/extra-addons/frepple
COPY freppledata /mnt/extra-addons/freppledata