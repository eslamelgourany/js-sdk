import uuid
import random
from textwrap import dedent

from jumpscale.sals.chatflows.chatflows import GedisChatBot, chatflow_step, StopChatFlow
from jumpscale.sals.reservation_chatflow import deployer, solutions
from jumpscale.loader import j


class GiteaDeploy(GedisChatBot):
    """
    gitea container deploy
    """

    steps = [
        "gitea_name",
        "select_pool",
        "gitea_network",
        "public_key_get",
        "gitea_credentials",
        "container_logs",
        "container_node_id",
        "container_ip",
        "overview",
        "reservation",
        "success",
    ]
    title = "Gitea"

    def _gitea_start(self):
        self.username = self.user_info()["username"]
        self.solution_id = uuid.uuid4().hex
        self.user_form_data = dict()
        self.threebot_name = j.data.text.removesuffix(self.user_info()["username"], ".3bot")
        self.HUB_URL = "https://hub.grid.tf/omar0.3bot/omarelawady-gitea_all_in_one-latest.flist"
        self.query = {"mru": 1, "cru": 2, "sru": 6}
        self.solution_metadata = {}

    @chatflow_step(title="Solution name")
    def gitea_name(self):
        self._gitea_start()
        valid = False
        while not valid:
            self.solution_name = deployer.ask_name(self)
            monitoring_solutions = solutions.list_gitea_solutions(sync=False)
            valid = True
            for sol in monitoring_solutions:
                if sol["Name"] == self.solution_name:
                    valid = False
                    self.md_show("The specified solution name already exists. please choose another.")
                    break
                valid = True

    @chatflow_step(title="Pool")
    def select_pool(self):
        cu, su = deployer.calculate_capacity_units(**self.query)
        self.pool_id = deployer.select_pool(self, cu=cu, su=su, **self.query)

    @chatflow_step(title="Network")
    def gitea_network(self):
        self.network_view = deployer.select_network(self)

    @chatflow_step(title="Access keys")
    def public_key_get(self):
        self.public_key = self.upload_file(
            """Please add your public ssh key, this will allow you to access the deployed container using ssh.
                    Just upload the file with the key""",
            required=True,
        ).split("\n")[0]

    @chatflow_step(title="Database credentials & Repository name")
    def gitea_credentials(self):
        form = self.new_form()
        database_name = form.string_ask(
            "Please add the database name of your gitea", default="postgres", required=True,
        )
        database_user = form.string_ask(
            "Please add the username for your gitea database. Make sure not to lose it",
            default="postgres",
            required=True,
        )
        database_password = form.string_ask(
            "Please add the secret for your gitea database. Make sure not to lose it",
            default="postgres",
            required=True,
        )
        repository_name = form.string_ask(
            "Please add the name of repository in your gitea", default="myrepo", required=True,
        )
        form.ask()
        self.database_name = database_name.value
        self.database_user = database_user.value
        self.database_password = database_password.value
        self.repository_name = repository_name.value

    @chatflow_step(title="Container logs")
    def container_logs(self):
        self.container_logs_option = self.single_choice(
            "Do you want to push the container logs (stdout and stderr) onto an external redis channel",
            ["YES", "NO"],
            default="NO",
        )
        if self.container_logs_option == "YES":
            self.log_config = deployer.ask_container_logs(self, self.solution_name)
        else:
            self.log_config = {}

    @chatflow_step(title="Container node id")
    def container_node_id(self):
        self.selected_node = deployer.ask_container_placement(self, self.pool_id, **self.query)
        if not self.selected_node:
            self.selected_node = deployer.schedule_container(self.pool_id, **self.query)

    @chatflow_step(title="Container IP")
    def container_ip(self):
        self.network_view_copy = self.network_view.copy()
        result = deployer.add_network_node(
            self.network_view.name,
            self.selected_node,
            self.pool_id,
            self.network_view_copy,
            bot=self,
            owner=self.solution_metadata.get("owner"),
        )
        if result:
            for wid in result["ids"]:
                success = deployer.wait_workload(wid, self, breaking_node_id=self.selected_node.node_id)
                if not success:
                    raise StopChatFlow(f"Failed to add node {self.selected_node.node_id} to network {wid}")
            self.network_view_copy = self.network_view_copy.copy()
        free_ips = self.network_view_copy.get_node_free_ips(self.selected_node)
        self.ip_address = self.drop_down_choice(
            "Please choose IP Address for your solution", free_ips, default=free_ips[0], required=True,
        )
        self.md_show_update("Preparing gateways ...")
        gateways = deployer.list_all_gateways()
        if not gateways:
            raise StopChatFlow("There are no available gateways in the farms bound to your pools.")

        domains = dict()
        for gw_dict in gateways.values():
            gateway = gw_dict["gateway"]
            for domain in gateway.managed_domains:
                domains[domain] = gw_dict

        self.domain = random.choice(list(domains.keys()))

        self.gateway = domains[self.domain]["gateway"]
        self.gateway_pool = domains[self.domain]["pool"]
        self.solution_name = self.solution_name.replace(".", "").replace("_", "-")
        self.domain = f"{self.threebot_name}-{self.solution_name}.{self.domain}"

        self.addresses = []
        for ns in self.gateway.dns_nameserver:
            self.addresses.append(j.sals.nettools.get_host_by_name(ns))

        self.secret = f"{j.core.identity.me.tid}:{uuid.uuid4().hex}"

    @chatflow_step(title="Confirmation")
    def overview(self):
        self.metadata = {
            "Solution Name": self.solution_name,
            "Network": self.network_view.name,
            "Node ID": self.selected_node.node_id,
            "Pool": self.pool_id,
            "IP Address": self.ip_address,
        }
        self.md_show_confirm(self.metadata)

    @chatflow_step(title="Reservation")
    def reservation(self):
        var_dict = {
            "pub_key": self.public_key,
            "POSTGRES_DB": self.database_name,
            "DB_TYPE": "postgres",
            "DB_HOST": "localhost:5432",
            "POSTGRES_USER": self.database_user,
            "APP_NAME": self.repository_name,
            "ROOT_URL": f"https://{self.domain}",
            "HTTP_PORT": "3000",
            "DOMAIN": f"{self.domain}",
        }
        metadata = {
            "name": self.solution_name,
            "form_info": {"Solution name": self.solution_name, "chatflow": "gitea",},
        }
        self.solution_metadata.update(metadata)
        # reserve subdomain
        subdomain_wid = deployer.create_subdomain(
            pool_id=self.pool_id,
            gateway_id=self.gateway.node_id,
            subdomain=self.domain,
            addresses=self.addresses,
            solution_uuid=self.solution_id,
            **self.solution_metadata,
        )
        subdomain_wid = deployer.wait_workload(subdomain_wid, self)

        if not subdomain_wid:
            raise StopChatFlow(
                f"Failed to create subdomain {self.domain} on gateway {self.gateway.node_id} {subdomain_wid}"
            )
        self.resv_id = deployer.deploy_container(
            pool_id=self.pool_id,
            node_id=self.selected_node.node_id,
            network_name=self.network_view.name,
            ip_address=self.ip_address,
            flist=self.HUB_URL,
            cpu=2,
            memory=1024,
            env=var_dict,
            interactive=False,
            entrypoint="/start_gitea.sh",
            log_config=self.log_config,
            public_ipv6=True,
            disk_size=6 * 1024,
            secret_env={"POSTGRES_PASSWORD": self.database_password},
            **self.solution_metadata,
            solution_uuid=self.solution_id,
        )
        success = deployer.wait_workload(self.resv_id, self)
        if not success:
            solutions.cancel_solution([self.resv_id])
            raise StopChatFlow(f"Failed to deploy workload {self.resv_id}")

        self.reverse_proxy_id = deployer.expose_and_create_certificate(
            pool_id=self.pool_id,
            gateway_id=self.gateway.node_id,
            network_name=self.network_view.name,
            trc_secret=self.secret,
            domain=self.domain,
            email=self.user_info()["email"],
            solution_ip=self.ip_address,
            solution_port=3000,
            enforse_https=True,
            node_id=self.selected_node.node_id,
            solution_uuid=self.solution_id,
            proxy_pool_id=self.gateway_pool.pool_id,
            **self.solution_metadata,
        )
        success = deployer.wait_workload(self.reverse_proxy_id)
        if not success:
            solutions.cancel_solution([self.reverse_proxy_id])
            raise StopChatFlow(f"Failed to reserve tcprouter container workload {self.reverse_proxy_id}")

    @chatflow_step(title="Success", disable_previous=True, final_step=True)
    def success(self):
        message = f"""\
# Congratulations! Your own instance from gitea deployed successfully:
\n<br />\n
- You can access it via the browser using: <a href="https://{self.domain}" target="_blank">https://{self.domain}</a>
\n<br />\n
- This domain maps to your container with ip: `{self.ip_address}`
                """
        self.md_show(dedent(message), md=True)


chat = GiteaDeploy
