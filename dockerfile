FROM odoo:16

USER root

RUN echo "list_db = False" >> /etc/odoo/odoo.conf && \
    echo "limit_time_cpu = 600" >> /etc/odoo/odoo.conf && \
    echo "limit_time_real = 600" >> /etc/odoo/odoo.conf

USER odoo

# Option 1: download from github
# ADD https://api.github.com/repos/frepple/odoo/compare/16.0...HEAD /dev/null
# RUN cd /mnt/extra-addons && \
#    curl -L https://github.com/frePPLe/odoo/archive/16.0.tar.gz | tar -xz --strip-components=1

# Option 2: copy local files into docker image
COPY autologin /mnt/extra-addons/autologin
COPY frepple /mnt/extra-addons/frepple
COPY freppledata /mnt/extra-addons/freppledata