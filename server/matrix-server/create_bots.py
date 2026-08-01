import hmac
import hashlib
import json
import urllib.request
import urllib.error
import time

HOMESERVER = "http://localhost:8008"
SHARED_SECRET = "zUu&~T_.kV^83gU4#faW:U7*#p8Mt,yVJGDRJ4A;0Mm74-:#Ew"
SERVER_NAME = "localhost"

# Helper function to send requests with retry
def make_request(url, data=None, headers=None, method='POST', max_retries=10):
    for attempt in range(max_retries):
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
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    err_body = e.read().decode('utf-8')
                    err_data = json.loads(err_body)
                    retry_after = err_data.get("retry_after_ms", 1000)
                    wait_time = (retry_after / 1000.0) + 0.1
                    print(f"Rate limited (429) on {url}. Retrying after {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                    continue
                except Exception:
                    time.sleep(1.0)
                    continue
            
            print(f"HTTP Error {e.code} requesting {url}: {e.reason}")
            try:
                err_body = e.read().decode('utf-8')
                print(f"Error Details: {err_body}")
                return json.loads(err_body)
            except Exception:
                pass
            return None
        except Exception as e:
            print(f"Error requesting {url}: {e}")
            time.sleep(1.0)
            continue
    print(f"Max retries reached for {url}")
    return None

def register_user(username, displayname, admin=False, creator_token=None):
    admin_api_url = f"{HOMESERVER}/_synapse/admin/v1/register"
    user_id = f"@{username}:{SERVER_NAME}"
    
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
        token = res["access_token"]
        user_id = res["user_id"]
        device_id = res.get("device_id", "")
        # Set display name
        headers = {"Authorization": f"Bearer {token}"}
        disp_url = f"{HOMESERVER}/_matrix/client/v3/profile/{user_id}/displayname"
        make_request(disp_url, data={"displayname": displayname}, headers=headers, method='PUT')
        
        # If device_id not returned, fetch it
        if not device_id:
            dev_url = f"{HOMESERVER}/_matrix/client/v3/devices"
            dev_res = make_request(dev_url, headers=headers, method='GET')
            if dev_res and "devices" in dev_res and len(dev_res["devices"]) > 0:
                device_id = dev_res["devices"][0].get("device_id", "")
                
        print(f"Registered bot/user: {user_id} ({displayname}) - Device: {device_id}")
        return {"user_id": user_id, "token": token, "device_id": device_id, "display_name": displayname}
    else:
        # User already exists
        # If we have creator_token, use the Admin Impersonation API to bypass rate limits
        if creator_token:
            admin_login_url = f"{HOMESERVER}/_synapse/admin/v1/users/{user_id}/login"
            headers = {"Authorization": f"Bearer {creator_token}"}
            login_res = make_request(admin_login_url, data={}, headers=headers, method='POST')
            if login_res and "access_token" in login_res:
                token = login_res["access_token"]
                
                # Fetch device ID
                device_id = ""
                dev_headers = {"Authorization": f"Bearer {token}"}
                dev_url = f"{HOMESERVER}/_matrix/client/v3/devices"
                dev_res = make_request(dev_url, headers=dev_headers, method='GET')
                if dev_res and "devices" in dev_res and len(dev_res["devices"]) > 0:
                    device_id = dev_res["devices"][0].get("device_id", "")
                
                print(f"Logged in user {username} via Admin API - Device: {device_id}")
                return {"user_id": user_id, "token": token, "device_id": device_id, "display_name": displayname}
                
        # Fallback to normal login
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
            token = login_res["access_token"]
            user_id = login_res["user_id"]
            device_id = login_res.get("device_id", "")
            
            headers = {"Authorization": f"Bearer {token}"}
            if not device_id:
                dev_url = f"{HOMESERVER}/_matrix/client/v3/devices"
                dev_res = make_request(dev_url, headers=headers, method='GET')
                if dev_res and "devices" in dev_res and len(dev_res["devices"]) > 0:
                    device_id = dev_res["devices"][0].get("device_id", "")
                    
            print(f"User {username} already exists, logged in - Device: {device_id}")
            return {"user_id": user_id, "token": token, "device_id": device_id, "display_name": displayname}
        else:
            print(f"Failed to register/login user {username}: {res}")
            return None

def join_user_to_room(user_token, room_id):
    if not room_id:
        return
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/join"
    headers = {"Authorization": f"Bearer {user_token}"}
    make_request(url, data={}, headers=headers)

def main():
    unique_admin = f"demo_admin_{int(time.time())}"
    print(f"Registering unique admin {unique_admin}...")
    creator = register_user(unique_admin, "OUK System Admin", admin=True)
    if not creator:
        print("Failed to get creator token.")
        return
        
    # Get all rooms to find their IDs
    rooms_url = f"{HOMESERVER}/_synapse/admin/v1/rooms"
    headers = {"Authorization": f"Bearer {creator['token']}"}
    rooms_res = make_request(rooms_url, headers=headers, method='GET')
    
    if not rooms_res or "rooms" not in rooms_res:
        print("Failed to list rooms.")
        return
        
    room_map = {r["name"]: r["room_id"] for r in rooms_res["rooms"] if "name" in r and r["name"]}
    print(f"Discovered rooms: {list(room_map.keys())}")
    
    # Bots to create
    bots_config = {
        "somas_bot": {
            "display_name": "SOMAS Bot",
            "rooms": ["CS Notices & Announcements", "CS Discussion Forum", "Programming Q&A"]
        },
        "group_bot": {
            "display_name": "Group Bot",
            "rooms": [
                "CS Notices & Announcements", "CS Discussion Forum", "Programming Q&A", "CS Demo Group Project",
                "Unit: Business Entrepreneurship", "Clubs Announcements", "Tech & Coding Club", "Drama & Art Club",
                "Sports & Athletics Club", "Communities Notices", "Christian Union (CU)", "Catholic Students Association",
                "Muslim Students Association", "OUK Announcements", "General Q&A Portal"
            ] # Joins all groups/classes
        },
        "info_bot": {
            "display_name": "Info Bot",
            "rooms": ["OUK Announcements", "General Q&A Portal"]
        },
        "bible_bot": {
            "display_name": "Bible Bot",
            "rooms": ["Christian Union (CU)"]
        },
        "class_bot": {
            "display_name": "Class Bot",
            "rooms": ["CS Notices & Announcements", "CS Discussion Forum", "Programming Q&A", "CS Demo Group Project"]
        },
        "support_bot": {
            "display_name": "Student Support Bot",
            "rooms": ["General Q&A Portal"]
        }
    }
    
    bot_details = []
    
    for username, config in bots_config.items():
        print(f"Setting up bot: {username}...")
        bot = register_user(username, config["display_name"], creator_token=creator["token"])
        if bot:
            # Join specified rooms
            for room_name in config["rooms"]:
                room_id = room_map.get(room_name)
                if room_id:
                    print(f"Joining {username} to {room_name} ({room_id})")
                    join_user_to_room(bot["token"], room_id)
                else:
                    print(f"Room '{room_name}' not found for joining.")
            bot_details.append(bot)
            
    # Output JSON and Markdown
    print("\nBot setup complete! Detailed credentials:\n")
    print(json.dumps(bot_details, indent=2))
    
    # Write to a file in the workspace
    with open("bot_details.json", "w") as f:
        json.dump(bot_details, f, indent=2)
        
    print("Bot details saved to bot_details.json")

if __name__ == "__main__":
    main()
