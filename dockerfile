FROM odoo:12

USER root

RUN pip3 install --no-cache-dir Pyjwt && \
    echo "list_db = False" >> /etc/odoo/odoo.conf

USER odoo

# Option 1: download from github
# ADD https://api.github.com/repos/frepple/odoo/compare/12.0...HEAD /dev/null
# RUN cd /mnt/extra-addons && \
#    curl -L https://github.com/frePPLe/odoo/archive/12.0.tar.gz | tar -xz --strip-components=1

# Option 2: copy local files into docker image
COPY frepple /mnt/extra-addons/frepple