import logging
from typing import Optional, Tuple, Callable, Awaitable
from urllib.parse import urlencode
from synapse.module_api import ModuleApi, JsonDict, LoginResponse

logger = logging.getLogger(__name__)

class MoodleAuthProvider:
    def __init__(self, config: dict, module_api: ModuleApi):
        self._api = module_api
        self._moodle_url = config.get("moodle_url", "https://somas.ouk.ac.ke")
        self._moodle_service = config.get("moodle_service", "moodle_mobile_app")
        
        # Register both standard password check and 3PID email auth callbacks
        self._api.register_password_auth_provider_callbacks(
            auth_checkers={
                ("m.login.password", ("password",)): self.check_auth
            },
            check_3pid_auth=self.check_3pid_auth
        )
        logger.info(
            "Initialized MoodleAuthProvider with Moodle URL: %s, Service: %s",
            self._moodle_url,
            self._moodle_service
        )

    @staticmethod
    def parse_config(config: dict) -> dict:
        if "moodle_url" not in config:
            config["moodle_url"] = "https://somas.ouk.ac.ke"
        if "moodle_service" not in config:
            config["moodle_service"] = "moodle_mobile_app"
        return config

    async def check_auth(
        self, user: str, login_type: str, login_dict: JsonDict
    ) -> Optional[Tuple[str, Optional[Callable[[LoginResponse], Awaitable[None]]]]]:
        
        password = login_dict.get("password")
        if not user or not password:
            return None

        # Clean user identifier to get localpart
        localpart = user
        if localpart.startswith("@"):
            if ":" in localpart:
                localpart = localpart.split(":")[0][1:]
            else:
                localpart = localpart[1:]
        
        # If user identifier contains an email address (e.g. ST04352752025@students.ouk.ac.ke)
        address = user
        if "@" in user and not user.startswith("@"):
            localpart = user.split("@")[0].lower()
        else:
            # Fallback format for binding if only username was provided
            address = f"{localpart}@students.ouk.ac.ke"

        logger.info("Attempting Moodle user auth for user: %s (localpart: %s)", user, localpart)

        token = await self._authenticate_moodle(address, localpart, password)
        if not token:
            return None

        fullname = await self._get_moodle_fullname(token, localpart)
        
        try:
            await self._register_local_user(localpart, fullname)
        except Exception as re:
            logger.error("Failed to ensure user %s exists locally: %s", localpart, re)
            return None
        
        user_mxid = f"@{localpart}:{self._api.server_name}"
        await self._associate_3pid(user_mxid, "email", address)

        return (user_mxid, None)

    async def check_3pid_auth(
        self, medium: str, address: str, password: str
    ) -> Optional[Tuple[str, Optional[Callable[[LoginResponse], Awaitable[None]]]]]:
        
        if medium != "email":
            return None
            
        logger.info("Attempting Moodle 3PID auth for email: %s", address)
        
        localpart = address.split("@")[0].lower()
        
        token = await self._authenticate_moodle(address, localpart, password)
        if not token:
            return None
            
        fullname = await self._get_moodle_fullname(token, localpart)
        
        try:
            await self._register_local_user(localpart, fullname)
        except Exception as re:
            logger.error("Failed to ensure user %s exists locally: %s", localpart, re)
            return None
        
        user_mxid = f"@{localpart}:{self._api.server_name}"
        await self._associate_3pid(user_mxid, medium, address)
        
        return (user_mxid, None)

    async def _authenticate_moodle(self, address: str, localpart: str, password: str) -> Optional[str]:
        # Attempt 1: Authenticate with the full email address
        token = await self._get_token(address, password)
        if token:
            return token
            
        # Attempt 2: If the email address fails, try authenticating with just the localpart (e.g., student registration number)
        if localpart != address:
            logger.info("Moodle token request failed with email address, retrying with localpart: %s", localpart)
            token = await self._get_token(localpart, password)
            if token:
                return token
                
        return None

    async def _get_token(self, username: str, password: str) -> Optional[str]:
        try:
            query = urlencode({
                "username": username,
                "password": password,
                "service": self._moodle_service
            })
            token_url = f"{self._moodle_url.rstrip('/')}/login/token.php?{query}"
            result = await self._api.http_client.get_json(token_url)
            
            if result and "token" in result:
                return result["token"]
                
            error_msg = result.get("error") if result else "Empty response"
            logger.warning("Moodle token request failed for user %s: %s", username, error_msg)
        except Exception as e:
            logger.error("Exception requesting Moodle token for user %s: %s", username, e)
        return None

    async def _get_moodle_fullname(self, token: str, localpart: str) -> Optional[str]:
        try:
            query_info = urlencode({
                "wstoken": token,
                "wsfunction": "core_webservice_get_site_info",
                "moodlewsrestformat": "json"
            })
            info_url = f"{self._moodle_url.rstrip('/')}/webservice/rest/server.php?{query_info}"
            info = await self._api.http_client.get_json(info_url)
            
            if info and "fullname" in info:
                fullname = info["fullname"]
                logger.info("Retrieved fullname for user %s: %s", localpart, fullname)
                return fullname
        except Exception as e:
            logger.error("Exception retrieving Moodle profile info for %s: %s", localpart, e)
        return None

    async def _register_local_user(self, localpart: str, fullname: Optional[str]) -> None:
        user_mxid = f"@{localpart}:{self._api.server_name}"
        try:
            # Register user without display name first
            await self._api.register_user(localpart=localpart)
            logger.info("Registered new local Matrix user: %s", localpart)
            
            # Set the display name if provided
            if fullname:
                try:
                    await self._api.set_displayname(user_mxid, fullname)
                    logger.info("Set displayname for %s: %s", user_mxid, fullname)
                except Exception as de:
                    logger.error("Error setting displayname for %s: %s", user_mxid, de)
        except Exception as e:
            if getattr(e, "errcode", None) == "M_USER_IN_USE":
                logger.info("Local Matrix user %s already exists", localpart)
                # If user already exists, update their display name if needed
                if fullname:
                    try:
                        await self._api.set_displayname(user_mxid, fullname)
                    except Exception as de:
                        logger.warning("Failed to update display name for existing user %s: %s", user_mxid, de)
            else:
                logger.error("Error registering local Matrix user %s: %s", localpart, e)
                raise e

    async def _associate_3pid(self, user_mxid: str, medium: str, address: str) -> None:
        try:
            store = None
            hs = getattr(self._api, "_hs", None)
            if hs:
                if hasattr(hs, "get_profile_handler"):
                    store = hs.get_profile_handler().store
                elif hasattr(hs, "get_datastores"):
                    store = hs.get_datastores().main
                elif hasattr(hs, "get_datastore"):
                    store = hs.get_datastore()
            
            if store:
                import time
                now = int(time.time() * 1000)
                await store.user_add_threepid(user_mxid, medium, address, now, now)
                logger.info("Successfully associated 3PID %s (%s) with %s", address, medium, user_mxid)
            else:
                logger.warning("Could not obtain Synapse datastore to associate 3PID")
        except Exception as e:
            logger.error("Failed to associate 3PID %s with %s: %s", address, user_mxid, e)
