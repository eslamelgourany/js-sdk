from jumpscale.sals.reservation_chatflow.deployer import DeploymentFailed
from .base_component import VDCBaseComponent
from jumpscale.clients.explorer.models import WorkloadType
from jumpscale.sals.reservation_chatflow import deployer
from jumpscale.loader import j
import gevent
import random
import uuid
from .scheduler import Scheduler


class VDCProxy(VDCBaseComponent):
    def __init__(self, vdc_deployer, farm_name=None):
        super().__init__(vdc_deployer)
        self._farm_name = farm_name
        self._farm = None

    @property
    def farm(self):
        if not self._farm:
            self._farm = self.explorer.farms.get(farm_name=self.farm_name)
        return self._farm

    @property
    def farm_name(self):
        if not self._farm_name:
            gateways = self.explorer.gateway.list()
            random.shuffle(gateways)
            for gateway in gateways:
                if not self.zos.nodes_finder.filter_is_up(gateway):
                    continue
                if not gateway.dns_nameserver:
                    continue
                farm_id = gateway.farm_id
                try:
                    farm = self.explorer.farms.get(farm_id)
                    self._farm_name = farm.name
                    break
                except Exception as e:
                    self.vdc_deployer.error(f"failed to fetch farm with id {farm_id} due to error {str(e)}")
                    continue

        return self._farm_name

    def fetch_myfarm_gateways(self):
        farm_gateways = []
        for gateway in self.explorer.gateway.list(farm_id=self.farm.id):
            if not self.zos.nodes_finder.filter_is_up(gateway):
                continue
            if not gateway.dns_nameserver:
                continue
            farm_gateways.append(gateway)
        return farm_gateways

    def get_gateway_pool_id(self):
        """
        return a pool id on my farm that has available gateway
        """
        self.vdc_deployer.info(f"looking for pool with gateways within farm: {self.farm_name}")
        farm_gateways = self.fetch_myfarm_gateways()
        if not farm_gateways:
            self.vdc_deployer.error(f"no gateways available in farm: {self.farm_name}")
            return

        self.vdc_deployer.info(f"looking for existing pools that contain gateways of farm: {self.farm_name}")
        gateway_node_ids = [node.node_id for node in farm_gateways]
        for pool in self.zos.pools.list():
            if list(set(pool.node_ids) & set(gateway_node_ids)):
                self.vdc_deployer.info(
                    f"found pool with available gateways on farm: {self.farm_name} pool_id: {pool.pool_id}"
                )
                return pool.pool_id

        self.vdc_deployer.info(f"reserving an empty pool on farm: {self.farm_name}")
        # no pool was found need to create a pool
        pool_info = self.zos.pools.create(0, 0, self.farm_name)
        self.vdc_deployer.info(f"gateway pool: {pool_info.reservation_id}")
        return pool_info.reservation_id

    def get_gateway_addresses(self, gateway):
        addresses = []
        for nameserver in gateway.dns_nameserver:
            try:
                self.vdc_deployer.info(f"resolving name: {nameserver} of gateway {gateway.node_id}")
                addresses.append(j.sals.nettools.get_host_by_name(nameserver))
            except Exception as e:
                self.vdc_deployer.error(
                    f"failed to resolve dns: {nameserver} of gateway {gateway.node_id} due to error {str(e)}"
                )
                continue
        return addresses

    @staticmethod
    def check_domain_availability(domain):
        try:
            ip = j.sals.nettools.get_host_by_name(domain)
            if ip:
                return True
        except:
            return False

    def wait_domain_population(self, domain, timeout=5):
        end = j.data.time.now().timestamp + timeout * 60
        while j.data.time.now().timestamp < end:
            if self.check_domain_availability(domain):
                return True
            gevent.sleep(3)
        return False

    def reserve_subdomain(self, gateway, prefix, vdc_uuid, pool_id=None, ip_address=None):
        """
        it will try to create a working subdomain on any of the available managed domain of the gateway
        Args:
            gateway: gateway to use
            prefix: the prefix that will be added to the managed domain
            ip_address: which the subdomain will point to. by default will point to the chosen gateway

        yields:
            subdomain
            workload id
        """
        pool_id = pool_id or self.get_gateway_pool_id()
        if not pool_id:
            return None

        random.shuffle(gateway.managed_domains)
        for managed_domain in gateway.managed_domains:
            self.vdc_deployer.info(f"reserving subdomain of {managed_domain}")
            subdomain = f"{prefix}.{managed_domain}"
            addresses = None
            # check availability of the subdomain

            if self.check_domain_availability(subdomain):
                self.vdc_deployer.error(f"subdomain {subdomain} already exists")
                continue

            if ip_address:
                addresses = [ip_address]
            else:
                addresses = self.get_gateway_addresses(gateway)
            # check resolvable names of the gateway dns servers
            if not addresses:
                self.vdc_deployer.error(f"gateway {gateway.node_id} doesn't have any valid nameservers configured")
                break
            # check population of the managed domain
            if not deployer.test_managed_domain(
                gateway.node_id, managed_domain, pool_id, gateway, self.identity.instance_name
            ):
                self.vdc_deployer.error(
                    f"population of managed domain {managed_domain} failed on gateway {gateway.node_id}"
                )
                continue

            # reserve subdomain
            wid = deployer.create_subdomain(
                pool_id,
                gateway.node_id,
                subdomain,
                addresses,
                identity_name=self.identity.instance_name,
                solution_uuid=vdc_uuid,
            )
            try:
                success = deployer.wait_workload(wid, bot=self.bot, identity_name=self.identity.instance_name)
                if not success:
                    raise DeploymentFailed()
            except DeploymentFailed:
                self.vdc_deployer.error(f"subdomain {subdomain} failed. wid: {wid}")
                continue

            populated = self.wait_domain_population(subdomain)
            if populated:
                self.vdc_deployer.info(f"subdomain {subdomain} created successfully pointing to {addresses}")
                yield subdomain, wid
            else:
                self.vdc_deployer.error(f"subdomain {subdomain} failed to populate wid: {wid}")
                self.zos.workloads.decomission(wid)
        self.vdc_deployer.error(f"all tries to reserve a subdomain failed on farm {self.farm_name}")

    def proxy_container(self, prefix, wid, port, vdc_uuid, pool_id=None, secret=None, scheduler=None):
        secret = secret or uuid.uuid4().hex
        secret = f"{self.identity.tid}:{secret}"
        scheduler = scheduler or Scheduler(self.farm_name)
        print("scheduler object id: ", id(scheduler))
        self.vdc_deployer.info(f"proxy container {wid} port {port} pool: {pool_id}")
        workload = self.zos.workloads.get(wid)
        if workload.info.workload_type != WorkloadType.Container:
            raise j.exceptions.Validation(f"can't expose workload {wid} of type {workload.info.workload_type}")

        pool_id = pool_id or workload.info.pool_id

        ip_address = workload.network_connection[0].ipaddress
        gateways = self.fetch_myfarm_gateways()
        random.shuffle(gateways)
        gateway_pool_id = self.get_gateway_pool_id()
        for gateway in gateways:
            for subdomain, subdomain_id in self.reserve_subdomain(gateway, prefix, vdc_uuid, gateway_pool_id):
                cont_id = None
                proxy_id = None
                for node in scheduler.nodes_by_capacity(cru=1, mru=1, sru=0.25):
                    try:
                        self.vdc_deployer.info(
                            f"deploying proxy for wid: {wid} on node: {node.node_id} subdomain: {subdomain} gateway: {gateway.node_id}"
                        )
                        cont_id, proxy_id = deployer.expose_and_create_certificate(
                            pool_id=pool_id,
                            gateway_id=gateway.node_id,
                            network_name=self.vdc_name,
                            trc_secret=secret,
                            domain=subdomain,
                            email=self.vdc_deployer.email,
                            solution_ip=ip_address,
                            solution_port=port,
                            enforce_https=True,
                            proxy_pool_id=gateway_pool_id,
                            bot=self.bot,
                            solution_uuid=vdc_uuid,
                            secret=secret,
                            node_id=node.node_id,
                            wid=wid,
                            identity_name=self.identity.instance_name,
                        )
                        success = deployer.wait_workload(cont_id, self.bot, identity_name=self.identity.instance_name)
                        if not success:
                            self.vdc_deployer.error(
                                f"nginx container for wid: {wid} failed on node: {node.node_id} nginx_wid: {cont_id}"
                            )
                            # container only failed. no need to decomission subdomain
                            self.zos.workloads.decomission(proxy_id)
                            continue
                        return cont_id
                    except DeploymentFailed:
                        self.vdc_deployer.error(
                            f"proxy reservation for wid: {wid} failed on node: {node.node_id} subdomain: {subdomain} gateway: {gateway.node_id}"
                        )
                        if cont_id:
                            self.zos.workloads.decomission(cont_id)
                        if proxy_id:
                            self.zos.workloads.decomission(proxy_id)
                        continue
                self.zos.workloads.decomission(subdomain_id)
                self.vdc_deployer.error(f"failed to proxy wid: {wid} on subdomain {subdomain}")
                scheduler.refresh_nodes()
            self.vdc_deployer.error(f"failed to expose workload {wid} on gateway {gateway.node_id}")
        self.vdc_deployer.error(f"all tries to expose wid {wid} failed")