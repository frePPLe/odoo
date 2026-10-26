# -*- coding: utf-8 -*-
#
# Copyright (C) 2025 by frePPLe bv
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

from datetime import datetime, timedelta
import gzip
import html
import json
import logging
import markupsafe
from odoo import fields, models, api, release
from odoo.exceptions import ValidationError
import os
from pathlib import Path
import re
import requests
import secrets
from tempfile import NamedTemporaryFile
import time
from werkzeug.security import check_password_hash, generate_password_hash

from ..controllers.frepplexml import encode_jwt
from ..controllers.outbound import exporter, Odoo_generator

logger = logging.getLogger(__name__)


class FreppleJob(models.Model):
    _name = "frepple.job"
    _description = "Frepple Jobs"

    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )
    status = fields.Char("status")
    user_id = fields.Many2one(
        "res.users", string="Submitted by", default=lambda self: self.env.user
    )
    started = fields.Datetime(string="Date when the job was launched")
    finished = fields.Datetime(string="Date when a response was received from frePPLe")
    hashed_token = fields.Char(string="Hashed secret token", groups="base.group_system")
    constraints = fields.Char(string="Constraints enabled for this job")

    @api.model
    def findJob(self, token):
        for j in self.env["frepple.job"].search(
            [
                ("finished", "=", False),
                ("status", "=", "Waiting for results"),
                (
                    "started",
                    ">",
                    (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            ],
            order="started asc",
        ):
            if check_password_hash(j.hashed_token, token):
                return j
        return None

    def action_cancel(self):
        for rec in self:
            rec.status = "cancelled"

    def action_start(self):
        for rec in self:
            rec.status = "started"
            rec.started = fields.Datetime.now()

    @api.model
    def get_allowed_companies(self):
        return [
            {
                "id": c.id,
                "name": c.name,
                "frepple_server": c.frepple_server or "",
            }
            for c in self.env.companies
        ]

    @api.model
    def get_last_constraints(self, company_id):
        last_job = self.env["frepple.job"].search(
            [
                ("company_id.id", "=", company_id),
                ("constraints", "!=", False),
            ],
            order="started desc",
            limit=1,
        )
        if last_job and last_job.constraints:
            enabled = last_job.constraints.split(",")
            return {
                "capacity": "capa" in enabled,
                "mfgLeadTime": "mfg_lt" in enabled,
                "poLeadTime": "po_lt" in enabled,
            }
        return None

    @api.model
    def get_status(self, company_id):
        # Check if settings are configured
        company = self.env["res.company"].browse(company_id)

        config_ok = True
        webtoken_key = company.getWebtoken_key()
        frepple_server = company.getFrepple_server()

        if not webtoken_key or not frepple_server:
            config_ok = False

        if not config_ok:
            url = "/odoo/settings#frepple"
            message = markupsafe.Markup(
                f'You must first set the <a href="{url}" class="fw-bold">frepple settings</a> '
                "properly before you can generate recommendations"
            )
            return {
                "message": message,
                "is_running": False,
                "last_update_date": False,
                "settings_missing": True,
            }
        last_job = self.env["frepple.job"].search(
            [
                ("company_id.id", "=", company_id),
                ("finished", "!=", False),
            ],
            order="finished desc",
            limit=1,
        )
        running_job = self.env["frepple.job"].search(
            [
                ("company_id.id", "=", company_id),
                ("finished", "=", False),
                ("status", "=", "Waiting for results"),
            ],
            order="started desc",
            limit=1,
        )

        # Make sure we don't have an old hanging job
        if running_job:
            running_job = (
                running_job
                if not last_job or running_job.started > last_job.started
                else None
            )

        failed = False
        if running_job:
            # Calculate duration
            now = fields.Datetime.now()
            duration = now - running_job.started
            seconds = int(duration.total_seconds())

            if seconds < 60:
                # Show seconds if under a minute
                elapsed_str = f"{seconds} seconds ago"
            else:
                # Show minutes and seconds
                minutes = seconds // 60
                rem_seconds = seconds % 60
                elapsed_str = f"{minutes}m {rem_seconds}s ago"

            message = f"started {elapsed_str} for {company.name}"
        else:
            if last_job:
                raw_utc_time = last_job[0].finished
                local_time = fields.Datetime.context_timestamp(self, raw_utc_time)
                constraint_labels = {
                    "capa": "capacity",
                    "mfg_lt": "manufacturing lead time",
                    "po_lt": "purchase lead time",
                }
                constraints_str = ""
                if last_job[0].constraints:
                    enabled = [
                        constraint_labels.get(c, c)
                        for c in last_job[0].constraints.split(",")
                        if c
                    ]
                    if enabled:
                        constraints_str = f" (respect {', '.join(enabled)})"
                if last_job[0].status == "Done":
                    # get the user time in the user time zone
                    message = f"Last refresh for {company.name}: {local_time.strftime('%Y-%m-%d %H:%M:%S')}{constraints_str}"
                else:
                    message = f"Last refresh for {company.name} failed at: {local_time.strftime('%Y-%m-%d %H:%M:%S')} - {last_job[0].status}"
                    failed = True
            else:
                message = f"Click on the generate recommendations button to get your first recommendations"

        return {
            "message": (
                markupsafe.Markup(message) if hasattr(markupsafe, "Markup") else message
            ),
            "is_running": True if running_job else False,
            "last_update_date": last_job.finished.isoformat() if last_job else False,
            "failed": failed,
        }

    @api.model
    def action_cancel_all(self, company_id):
        jobs_to_cancel = self.env["frepple.job"].search(
            [
                ("company_id.id", "=", company_id),
                ("finished", "=", False),
                ("status", "=", "Waiting for results"),
            ]
        )
        jobs_to_cancel.write({"status": "cancelled"})

    @api.model
    def action_launch(self, company_id, options=None):
        if options is None:
            options = {}

        company = self.env["res.company"].browse(company_id)
        if not company.exists():
            raise ValidationError(f"Company with id {company_id} does not exist.")

        missing = []
        if not company.webtoken_key:
            missing.append("Webtoken key")
        if not company.frepple_server:
            missing.append("frePPLe server")
        if missing:
            raise ValidationError(
                f"The following frePPLe settings are not configured for company "
                f"'{company.name}': {', '.join(missing)}. "
                f"Please go to Settings > frePPLe to configure them."
            )

        filename = None
        try:
            # Create a job and its token
            token = secrets.token_urlsafe(64)
            job = self.create(
                {
                    "status": "created",
                    "started": datetime.now(),
                    "user_id": self.env.user.id,
                    "hashed_token": generate_password_hash(token),
                    "company_id": company_id,
                }
            )

            job.write({"status": "Collecting data"})

            try:
                xp = exporter(
                    Odoo_generator(self.env),
                    None,
                    uid=self.env.user.id,
                    database=None,
                    company=company.name,
                    mode=1,
                    timezone=None,
                    singlecompany=True,
                    delta=999,
                    apps="",
                )
            except Exception as e:
                job.write(
                    {
                        "status": f"Error collecting data: {e}",
                        "finished": fields.Datetime.now(),
                    }
                )
                return

            # last empty double quote is to let python understand frepple is a folder.
            xml_folder = os.path.join(str(Path.home()), "logs", "frepple", "")
            os.makedirs(os.path.dirname(xml_folder), exist_ok=True)

            tmpfile = NamedTemporaryFile(mode="w+t", delete=False, dir=xml_folder)
            filename = tmpfile.name
            tmpfile.close()

            # Generate a file with all data
            with gzip.open(filename, "wb") as tmpfile:
                for i in xp.run():
                    tmpfile.write(i.encode("utf-8"))

            # Submitting the file to frepple
            job.write({"status": "Submitting data"})
            with open(filename, "rb") as f:
                constraint = []
                if options.get("capacity", True):
                    constraint.append("capa")
                if options.get("mfgLeadTime", True):
                    constraint.append("mfg_lt")
                if options.get("poLeadTime", True):
                    constraint.append("po_lt")

                job.write({"constraints": ",".join(constraint)})

                metadata = {
                    "email": self.env.user.email,
                    "odoo_url": self.env["ir.config_parameter"]
                    .sudo()
                    .get_str("web.base.url"),
                    "company": company.name,
                    "version": release.version,
                    "submitted": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "token": token,
                    "database": self.env.cr.dbname,
                    "constraint": ",".join(constraint),
                }

                webtoken = encode_jwt(
                    {"exp": round(time.time()) + 600, "user": self.env.user.login},
                    company.webtoken_key,
                )
                if not isinstance(webtoken, str):
                    webtoken = webtoken.decode("ascii")

                try:
                    response = requests.post(
                        f"{company.frepple_server.replace("localhost", "host.docker.internal")}/odoo/submit/",
                        headers={"Authorization": f"Bearer {str(webtoken)}"},
                        files={
                            "datafile": (
                                "odoodata.json",
                                f,
                                "application/octet-stream",
                            ),
                            "metadata": (
                                "metadata.json",
                                json.dumps(metadata),
                                "application/json",
                            ),
                        },
                        timeout=300,
                    )
                except requests.ConnectionError:
                    job.write(
                        {
                            "status": "Connection error",
                            "finished": fields.Datetime.now(),
                        }
                    )
                    return
                if response.status_code != 200:
                    raw_status = response.content.decode("utf-8", errors="replace")
                    plain_status = re.sub(r"<[^>]+>", "", raw_status)
                    plain_status = html.unescape(plain_status).strip()
                    plain_status = re.sub(r"\s+", " ", plain_status)
                    job.write(
                        {
                            "status": plain_status[:500],
                            "finished": fields.Datetime.now(),
                        }
                    )
                    logger.critical("Job submission failed.")
                    return
                else:
                    job.write({"status": "Waiting for results"})
        finally:
            if filename:
                os.remove(filename)
