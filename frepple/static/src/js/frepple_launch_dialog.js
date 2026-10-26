/** @odoo-module **/
import { Component, proxy, t, useProps, onWillStart } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";

export class FreppleLaunchDialog extends Component {
  static template = "frepple.LaunchDialog";
  static components = { Dialog };
  props = useProps({
    companies: t.array(t.object()),
    defaultCompanyId: t.number(),
    close: t.function(),
    onConfirm: t.function(),
  });

  setup() {
    this.orm = useService("orm");
    const initialCompanyId = this.props.companies.length === 1
      ? this.props.companies[0].id
      : this.props.defaultCompanyId;
    this.state = proxy({
      capacity: true,
      mfgLeadTime: true,
      poLeadTime: true,
      companyId: initialCompanyId,
    });
    onWillStart(() => this.loadLastConstraints(initialCompanyId));
  }

  async loadLastConstraints(companyId) {
    const result = await this.orm.call("frepple.job", "get_last_constraints", [companyId]);
    if (result) {
      this.state.capacity = result.capacity;
      this.state.mfgLeadTime = result.mfgLeadTime;
      this.state.poLeadTime = result.poLeadTime;
    } else {
      this.state.capacity = true;
      this.state.mfgLeadTime = true;
      this.state.poLeadTime = true;
    }
  }

  get isAnonymousServer() {
    const company = this.props.companies.find(c => c.id === this.state.companyId);
    const server = (company && company.frepple_server || "").replace(/\/+$/, "").toLowerCase();
    return server === "https://odoo.frepple.com";
  }

  onConfirm() {
    this.props.onConfirm({
      capacity: this.state.capacity,
      mfgLeadTime: this.state.mfgLeadTime,
      poLeadTime: this.state.poLeadTime,
      companyId: this.state.companyId,
    });
    this.props.close();
  }

  onCancel() {
    this.props.close();
  }

  onCapacityChange(ev) {
    this.state.capacity = ev.target.checked;
  }

  onMfgLeadTimeChange(ev) {
    this.state.mfgLeadTime = ev.target.checked;
  }

  onPoLeadTimeChange(ev) {
    this.state.poLeadTime = ev.target.checked;
  }

  onCompanyChange(ev) {
    this.state.companyId = parseInt(ev.target.value);
    this.loadLastConstraints(this.state.companyId);
  }
}
