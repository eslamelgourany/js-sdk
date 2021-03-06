from jumpscale.loader import j


class threebot_deployer:
    def install(self, **kwargs):
        """
        Args:
            wallet_secret (str, optional): if you have the wallet secret already activated you can pass it. Defaults to "STD".
            channel_type (str, optional): if you want to forward logs to redis for example
            channel_host (str, optional): hostname with public redis
            channel_port (int, optional): remote redis port
        """
        # Configure wallet
        WALLET_NAME = j.sals.marketplace.deployer.WALLET_NAME
        if WALLET_NAME not in j.clients.stellar.list_all():
            wallet_secret = kwargs.get("wallet_secret", None)
            wallet = j.clients.stellar.new(WALLET_NAME, secret=wallet_secret)

            if not wallet_secret:
                # mainnet, activate and add trustlines to an empty wallet
                wallet.activate_through_threefold_service()
                wallet.add_known_trustline("TFT")
                wallet.save()
            j.logger.info(f"Created wallet {WALLET_NAME} successfully and ready to use.")

        # Configure Redis logs
        log_config = {}
        log_config["channel_type"] = kwargs.get("channel_type")
        log_config["channel_host"] = kwargs.get("channel_host")
        log_config["channel_port"] = kwargs.get("channel_port")

        if all([v for v in log_config.values()]):
            j.core.config.set("LOGGING_SINK", log_config)
            j.logger.info(
                f"Added remote redis logs on machine {log_config['channel_host']}:{log_config['channel_port']}"
            )

    def start(self, **kwargs):
        # Configuring 3bot deployer package actors to be public
        location_actors_443 = j.sals.nginx.main.websites.default_443.locations.get(name="threebot_deployer_actors")
        location_actors_443.is_auth = False
        location_actors_443.is_admin = False
        location_actors_443.save()

        location_actors_80 = j.sals.nginx.main.websites.default_80.locations.get(name="threebot_deployer_actors")
        location_actors_80.is_auth = False
        location_actors_80.is_admin = False
        location_actors_80.save()

        j.sals.nginx.main.websites.default_443.configure()
        j.sals.nginx.main.websites.default_80.configure()

    def uninstall(self):
        """Called when package is deleted
        """
        j.sals.nginx.main.websites.default_443.locations.delete("threebot_deployer_root_proxy")
        j.sals.nginx.main.websites.default_80.locations.delete("threebot_deployer_root_proxy")
