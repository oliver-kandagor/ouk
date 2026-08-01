import hmac
import hashlib
import json
import urllib.request
import urllib.error
import time

HOMESERVER = "http://localhost:8008"
SHARED_SECRET = "zUu&~T_.kV^83gU4#faW:U7*#p8Mt,yVJGDRJ4A;0Mm74-:#Ew"
SERVER_NAME = "localhost"

# Helper function to send requests
def make_request(url, data=None, headers=None, method='POST'):
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data:
        req.data = json.dumps(data).encode('utf-8')
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"Error requesting {url}: {e}")
        if hasattr(e, 'read'):
            print(f"Response: {e.read().decode('utf-8')}")
        return None

def register_user(username, displayname, admin=False):
    admin_api_url = f"{HOMESERVER}/_synapse/admin/v1/register"
    
    # 1. Fetch nonce
    req = urllib.request.Request(admin_api_url, method='GET')
    try:
        with urllib.request.urlopen(req) as resp:
            nonce = json.loads(resp.read().decode('utf-8'))['nonce']
    except Exception as e:
        print(f"Failed to fetch nonce: {e}")
        return None
        
    # 2. Generate HMAC
    admin_str = "admin" if admin else "notadmin"
    mac = hmac.new(
        key=SHARED_SECRET.encode('utf-8'),
        digestmod=hashlib.sha1
    )
    mac.update(nonce.encode('utf-8'))
    mac.update(b"\x00")
    mac.update(username.encode('utf-8'))
    mac.update(b"\x00")
    mac.update(b"user") # Password is 'user'
    mac.update(b"\x00")
    mac.update(admin_str.encode('utf-8'))
    
    mac_digest = mac.hexdigest()
    
    # 3. Post registration
    payload = {
        "nonce": nonce,
        "username": username,
        "password": "user",
        "admin": admin,
        "mac": mac_digest
    }
    
    res = make_request(admin_api_url, data=payload)
    if res and "access_token" in res:
        return res["access_token"]
    else:
        # Fallback to login
        login_url = f"{HOMESERVER}/_matrix/client/v3/login"
        login_payload = {
            "type": "m.login.password",
            "identifier": {
                "type": "m.id.user",
                "user": username
            },
            "password": "user"
        }
        login_res = make_request(login_url, data=login_payload)
        if login_res and "access_token" in login_res:
            return login_res["access_token"]
    return None

def main():
    # Register a unique admin to perform password resets
    unique_admin = f"pwd_admin_{int(time.time())}"
    print(f"Registering admin: {unique_admin}...")
    token = register_user(unique_admin, "Password Reset Admin", admin=True)
    if not token:
        print("Failed to authenticate admin.")
        return
        
    bots = ["somas_bot", "group_bot", "info_bot", "bible_bot", "class_bot", "support_bot"]
    headers = {"Authorization": f"Bearer {token}"}
    
    for bot in bots:
        user_mxid = f"@{bot}:{SERVER_NAME}"
        url = f"{HOMESERVER}/_synapse/admin/v1/reset_password/{user_mxid}"
        payload = {
            "new_password": "user",
            "logout_devices": False
        }
        res = make_request(url, data=payload, headers=headers, method='POST')
        if res is not None:
            print(f"Successfully set password of {user_mxid} to 'user'.")
        else:
            print(f"Failed to reset password of {user_mxid}.")

if __name__ == "__main__":
    main()
