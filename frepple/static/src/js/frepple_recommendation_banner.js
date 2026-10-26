/** @odoo-module **/
import { ListController } from "@web/views/list/list_controller";
import { registry } from "@web/core/registry";
import { Component, proxy, t, useProps, onWillStart, onWillDestroy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { markup } from "@odoo/owl";
import { FreppleLaunchDialog } from "./frepple_launch_dialog";

export class FreppleRecommendationBanner extends Component {
  static template = "frepple.RecommendationBanner";
  props = useProps({ list: t.object().optional() });

  setup() {
    this.orm = useService("orm");
    this.notification = useService("notification");
    this.dialog = useService("dialog");

    this.state = proxy({
      message: "Loading...",
      isRunning: false, // track if a job is running
      lastUpdate: null,
      settingsMissing: false,
      failed: false,
    });

    this.companies = [];
    this.timer = null;

    onWillStart(async () => {
      await this.loadCompanies();
      await this.fetchData();
      this.startTimer();
    });

    onWillDestroy(() => {
      clearInterval(this.timer);
    });
  }

  async refreshList() {
    if (this.props.list) {
      await this.props.list.load();
    }
  }

  get currentCompanyId() {
    const cids = (document.cookie.match(/(^|;\s*)cids=([^;]*)/) || [])[2];
    if (cids) {
      return parseInt(cids.split("-")[0], 10);
    }
    return this.companies.length ? this.companies[0].id : 1;
  }

  async fetchData() {
    try {
      const companyId = this.currentCompanyId;

      const data = await this.orm.call("frepple.job", "get_status", [companyId]);

      // Detect if the data actually changed based on the timestamp
      const hasNewData =
        this.state.lastUpdate &&
        data.last_update_date &&
        this.state.lastUpdate !== data.last_update_date;

      this.state.message = markup(data.message);
      this.state.isRunning = data.is_running;
      this.state.lastUpdate = data.last_update_date;
      this.state.settingsMissing = !!data.settings_missing;
      this.state.failed = data.failed;

      if (hasNewData) {
        await this.refreshList();
      }

    } catch (error) {
      this.state.message = error;
      this.state.failed = true;
    }
  }

  startTimer() {
    this.timer = setInterval(() => this.fetchData(), 5000);
  }

  async onButtonClick() {

    // Safety check: prevent execution if settings are missing
    if (this.state.settingsMissing) {
      return;
    }

    const companyId = this.currentCompanyId;
    try {
      if (this.state.isRunning) {
        // Logic to cancel the job
        await this.orm.call("frepple.job", "action_cancel_all", [companyId]);
        await this.fetchData();
      } else {
        this.dialog.add(FreppleLaunchDialog, {
          companies: this.companies,
          defaultCompanyId: companyId,
          onConfirm: async (options) => {
            try {
              await this.orm.call("frepple.job", "action_launch", [options.companyId, {
                capacity: options.capacity,
                mfgLeadTime: options.mfgLeadTime,
                poLeadTime: options.poLeadTime,
              }]);
            } finally {
              await this.fetchData();
            }
          },
        });
      }
    } catch (error) {
      this.notification.add("Action failed", { type: "danger" });
    }
  }

  async loadCompanies() {
    try {
      this.companies = await this.orm.call("frepple.job", "get_allowed_companies", []);
    } catch {
      this.companies = [];
    }
  }

}

export class FreppleListController extends ListController {
  static template = "frepple.ListView";
  static components = { ...ListController.components, FreppleRecommendationBanner };
}

registry.category("views").add("frepple_recommendation_list", {
  ...registry.category("views").get("list"),
  Controller: FreppleListController,
});
