import uuid
from jumpscale.loader import j
from jumpscale.sals.chatflows.chatflows import GedisChatBot, chatflow_step, StopChatFlow
from jumpscale.sals.reservation_chatflow.models import SolutionType
from jumpscale.sals.reservation_chatflow import deployer, solutions


class FourToSixGateway(GedisChatBot):
    """
    """

    steps = [
        "select_pool",
        "gateway_start",
        "wireguard_public_get",
        "wg_reservation",
        "wg_config",
    ]
    title = "4to6 GW"

    @chatflow_step(title="Pool")
    def select_pool(self):
        self.solution_id = uuid.uuid4().hex
        self.pool_id = deployer.select_pool(self)

    @chatflow_step(title="Gateway")
    def gateway_start(self):
        self.gateway = deployer.select_gateway(self, self.pool_id)
        self.gateway_id = self.gateway.node_id

    @chatflow_step(title="Wireguard public key")
    def wireguard_public_get(self):
        self.publickey = self.string_ask(
            "Please enter wireguard public key or leave empty if you want us to generate one for you."
        )
        self.privatekey = "enter private key here"
        res = "# Click next to continue with wireguard related deployment. Once you proceed you will not be able to go back to this step"
        self.md_show(res, md=True)

    @chatflow_step(title="Create your Wireguard ", disable_previous=True)
    def wg_reservation(self):
        if not self.publickey:
            self.privatekey, self.publickey = j.tools.wireguard.generate_key_pair()

        self.resv_id = deployer.create_ipv6_gateway(
            self.gateway_id, self.pool_id, self.publickey, SolutionType="4to6GW", solution_uuid=self.solution_id
        )
        success = deployer.wait_workload(self.resv_id, self)
        if not success:
            raise StopChatFlow(f"Failed to deploy workload {self.resv_id}")
        self.reservation_result = j.sals.zos.workloads.get(self.resv_id).result
        res = """
# Use the following template to configure your wireguard connection. This will give you access to your network.
## Make sure you have <a target="_blank" href="https://www.wireguard.com/install/">wireguard</a> installed
Click next
to download your configuration
        """
        self.md_show(res)


chat = FourToSixGateway
