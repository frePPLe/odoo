from dateutil import tz
from odoo import fields, models, api, exceptions
import time
import jwt
import logging
import requests
from datetime import datetime


logger = logging.getLogger(__name__)


class Quote(models.Model):
    _name = "frepple.quote"
    _description = "Frepple Quote's"

    product_id = fields.Many2one("product.product", string="Product", required=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Warehouse", required=True)
    quantity = fields.Integer(string="Quantity", default=1, required=True)
    minimum_shipment = fields.Integer(string="Minimum Shipment", required=True)
    due_date = fields.Datetime(
        string="Due Date", default=lambda _: datetime.today(), required=True
    )
    maximum_lateness = fields.Integer(
        string="Maximum Lateness (in days)", default=1000, required=True
    )
    promised_delivery_date = fields.Datetime(
        string="Promised Delivery Date", readonly=True
    )
    detailed_quote = fields.Html(string="Detailed Quote Info", readonly=True)
    last_quoted = fields.Datetime(readonly=True)

    @api.depends("quantity")
    def _compute_minimum_shipment(self):
        for quote in self:
            if quote.quantity:
                quote.minimum_shipment = quote.quantity
            else:
                quote.minimum_shipment = 0

    def _generate_html(self, frepple_json):
        html = """
        <div style="font-family: \'Segoe UI\', Tahoma, Geneva, Verdana, sans-serif; padding: 20px; background-color: #f4f4f4; color: #333;">"""

        if frepple_json["demands"][0].get("pegging"):
            html = (
                html
                + """
            <div style="margin-bottom: 40px;">
                <h2 style="margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #3498db; color: #3498db;">Category: Operations</h2>
                <ul style="list-style-type: none; padding: 0;">
        """
            )
            for i, operation in enumerate(frepple_json["demands"][0]["pegging"]):
                if (
                    i != 0
                    and operation["level"]
                    <= frepple_json["demands"][0]["pegging"][i - 1]["level"]
                ):
                    for _ in range(
                        frepple_json["demands"][0]["pegging"][i - 1]["level"]
                        - operation["level"]
                        + 1
                    ):
                        html = (
                            html
                            + """
                            </div>
        """
                        )
                if i == 0:
                    html = (
                        html
                        + f"""
                        <li style="background-color: #fff; margin-bottom: 5px; padding: 15px; border-left: 5px solid #3498db;">
                            {operation["level"]} {operation["operationplan"]["operation"]["name"]}
                            <br />Quantity: {operation["operationplan"]["quantity"]}
                            <br />Start Date: {operation["operationplan"]["start"]}
                            <br />End Date: {operation["operationplan"]["end"]}
        """
                    )

                else:
                    if operation["level"] == 0:
                        html = (
                            html
                            + f"""
                        </li>
                        <li style="background-color: #fff; margin-bottom: 5px; padding: 15px; border-left: 5px solid #3498db;">
                            {operation["level"]} {operation["operationplan"]["operation"]["name"]}
                            <br />Quantity: {operation["operationplan"]["quantity"]}
                            <br />Start Date: {operation["operationplan"]["start"]}
                            <br />End Date: {operation["operationplan"]["end"]}
        """
                        )
                    else:
                        html = (
                            html
                            + f"""
                        <div style="margin-top: 10px; padding-left: 20px; border-left: 2px dashed #bdc3c7;">
                            <strong>Sub-operation: {operation["level"]}</strong>
                            <br>{operation["operationplan"]["operation"]["name"]}
                            <br>Quantity: {operation["operationplan"]["quantity"]}
                            <br>Start Date: {operation["operationplan"]["start"]}
                            <br>End Date: {operation["operationplan"]["end"]}
        """
                        )

            for i in range(
                frepple_json["demands"][0]["pegging"][
                    len(frepple_json["demands"][0]["pegging"]) - 1
                ]["level"]
            ):
                html = html + "</div>"
            html = (
                html
                + """
                    </li>
                </ul>
            </div>
        """
            )

        if frepple_json["demands"][0].get("problems"):
            html = (
                html
                + """
            <div style="margin-bottom: 40px;">
                <h2 style="margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #e74c3c; color: #e74c3c;">Category: Problems</h2>
                <ul style="list-style-type: none; padding: 0;">
        """
            )
            for problem in frepple_json["demands"][0]["problems"]:
                html = (
                    html
                    + f"""
                    <li style="background-color: #fff; margin-bottom: 5px; padding: 15px; border-left: 5px solid #e74c3c;">
                    {problem["description"]}
                    </li>
        """
                )
            html = (
                html
                + """
                </ul>
            </div>
        """
            )

        if frepple_json["demands"][0].get("constraints"):
            html = (
                html
                + """
            <div style="margin-bottom: 40px;">
                <h2 style="margin: 0 0 20px 0; padding-bottom: 10px; border-bottom: 3px solid #e74c3c; color: #e74c3c;">Category: Constraints</h2>
                <ul style="list-style-type: none; padding: 0;">
        """
            )
            for constraint in frepple_json["demands"][0]["constraints"]:
                html = (
                    html
                    + f"""
                    <li style="background-color: #fff; margin-bottom: 5px; padding: 15px; border-left: 5px solid #e74c3c;">
                    {constraint["description"]}
                    </li>
        """
                )
            html = (
                html
                + """
                </ul>
            </div>
        """
            )

        (
            html
            + html
            + """
        </div>
        """
        )
        return html

    def use_product_short_names(self):
        # Check if we can use short names
        # To use short names, the internal reference (or the name when no internal reference is defined)
        # needs to be unique
        use_short_names = True

        self.env.cr.execute(
            """
            select count(*) from
            (
            select coalesce(product_product.default_code,
            product_template.name->>%s,
            product_template.name->>'en_US'), count(*)
            from product_product
            inner join product_template on product_product.product_tmpl_id = product_template.id
            where product_template.type not in ('service', 'consu')
            group by coalesce(product_product.default_code,
            product_template.name->>%s,
            product_template.name->>'en_US')
            having count(*) > 1
            ) t
                """,
            (self.env.user.lang, self.env.user.lang),
        )
        for i in self.env.cr.fetchall():
            if i[0] > 0:
                use_short_names = False
                break
        return use_short_names

    def getfrePPLeItemName(self, product, use_short_names):
        if product.code:
            name = (
                (("[%s] %s" % (product.code, product.name))[:300])
                if not use_short_names
                else product.code[:300]
            )
        # product is a variant and has no internal reference
        # we use the product id as code
        elif product.product_template_attribute_value_ids:
            name = ("[%s] %s" % (product.id, product.name))[:300]
        else:
            name = product.name[:300]
        return name

    def action_quote(self):
        for quote in self:
            if quote.product_id and quote.warehouse_id and quote.quantity:

                request_body = {"demands": []}
                product_name = self.getfrePPLeItemName(
                    quote.product_id, self.use_product_short_names()
                )
                # The due date needs to be converted into the user time zone before sending it
                # to the quoting module of frepple
                due_date_utc = quote.due_date.replace(tzinfo=tz.gettz("UTC"))
                due_date_user_tz = due_date_utc.astimezone(
                    tz.gettz(self.env.user.tz)
                ).replace(tzinfo=None)

                request_body["demands"].append(
                    {
                        "name": quote.product_id.id,
                        "quantity": quote.quantity,
                        "description": "",
                        "due": due_date_user_tz.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                        "item": {"name": product_name},
                        "location": {"name": str(quote.warehouse_id.name)},
                        "customer": {"name": "All customers"},
                        "minshipment": quote.minimum_shipment,
                        "maxlateness": quote.maximum_lateness * 86400,
                        "priority": 20,
                    }
                )

                encode_params = dict(
                    exp=round(time.time()) + 600, user=quote.env.user.login
                )
                user_company_webtoken = quote.env.user.company_id.webtoken_key
                if not user_company_webtoken:
                    raise exceptions.UserError(
                        "FrePPLe company web token not configured"
                    )

                base_url = quote.env.user.company_id.frepple_server
                if not base_url:
                    raise exceptions.UserError("frePPLe web server not configured")
                if not base_url.endswith("/"):
                    base_url += "/"

                base_url = base_url.replace("8000", "8002")

                webtoken = jwt.encode(
                    encode_params, user_company_webtoken, algorithm="HS256"
                )
                if not isinstance(webtoken, str):
                    webtoken = webtoken.decode("ascii")

                # -----[ PERFORM THE REQUEST ]-----
                headers = {
                    "authorization": "Bearer " + str(webtoken),
                    "Content-Type": "application/json",
                }

                # Choose between quote or inquiry.
                action = "quote"
                # action = "inquiry"

                try:
                    frepple_response = requests.post(
                        "%ssvc/quote/%s/" % (base_url, action),
                        headers=headers,
                        json=request_body,
                    )
                except:
                    raise exceptions.UserError(
                        "The connection with the frePPLe quoting module could not be established"
                    )

                response_status_code = frepple_response.status_code

                if response_status_code == 401:
                    raise exceptions.UserError("User is not authorized to use FrePPLe")

                elif response_status_code != 200:
                    quote.promised_delivery_date = False
                    quote.detailed_quote = "N/A"
                    return

                response_json = frepple_response.json()
                if (
                    len(response_json["demands"]) > 0
                    and "pegging" in response_json["demands"][0]
                ):
                    if (
                        response_json["demands"][0]["pegging"][0]["operationplan"][
                            "end"
                        ]
                        != False
                    ):
                        promised_delivery_date_user_tz = datetime.strptime(
                            str(
                                response_json["demands"][0]["pegging"][0][
                                    "operationplan"
                                ]["end"]
                            ),
                            "%Y-%m-%dT%H:%M:%S",
                        ).replace(tzinfo=tz.gettz(self.env.user.tz))
                        promised_delivery_date_utc = (
                            promised_delivery_date_user_tz.astimezone(
                                tz.gettz("UTC")
                            ).replace(tzinfo=None)
                        )

                        quote.promised_delivery_date = promised_delivery_date_utc

                        quote.detailed_quote = self._generate_html(response_json)
                    else:
                        quote.promised_delivery_date = False
                        quote.detailed_quote = "N/A"
                else:
                    quote.promised_delivery_date = False
                    quote.detailed_quote = "N/A"

            else:
                quote.detailed_quote = (
                    "Please fill in all the required fields to receive a quote"
                )
                quote.quote = (
                    "Please fill in all the required fields to receive a quote"
                )

            quote.last_quoted = datetime.now()
