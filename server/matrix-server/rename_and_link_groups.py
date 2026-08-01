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
    except urllib.error.HTTPError as e:
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
        return None

def register_user(username, displayname, admin=False):
    admin_api_url = f"{HOMESERVER}/_synapse/admin/v1/register"
    req = urllib.request.Request(admin_api_url, method='GET')
    try:
        with urllib.request.urlopen(req) as resp:
            nonce = json.loads(resp.read().decode('utf-8'))['nonce']
    except Exception as e:
        return None
        
    admin_str = "admin" if admin else "notadmin"
    mac = hmac.new(SHARED_SECRET.encode("utf-8"), digestmod=hashlib.sha1)
    mac.update(nonce.encode("utf-8") + b"\x00" + username.encode("utf-8") + b"\x00" + b"user" + b"\x00" + admin_str.encode('utf-8'))
    payload = {"nonce": nonce, "username": username, "password": "user", "admin": admin, "mac": mac.hexdigest()}
    req = urllib.request.Request(admin_api_url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
    res = json.loads(urllib.request.urlopen(req).read().decode("utf-8"))
    return res.get("access_token")

def make_user_room_admin(admin_token, room_id, user_mxid):
    url = f"{HOMESERVER}/_synapse/admin/v1/rooms/{room_id}/make_room_admin"
    payload = {"user_id": user_mxid}
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    return make_request(url, data=payload, headers=headers, method='POST')

def main():
    admin_token = register_user(f"link_admin_{int(time.time())}", "Link Admin", admin=True)
    if not admin_token:
        print("Failed to get admin token.")
        return
        
    # Get all rooms
    rooms_url = f"{HOMESERVER}/_synapse/admin/v1/rooms"
    headers = {"Authorization": f"Bearer {admin_token}"}
    rooms_res = make_request(rooms_url, headers=headers, method='GET')
    
    if not rooms_res or "rooms" not in rooms_res:
        print("Failed to list rooms.")
        return
        
    room_map = {r["name"]: r["room_id"] for r in rooms_res["rooms"] if "name" in r and r["name"]}
    print("Discovered rooms:", list(room_map.keys()))
    
    # 1. Find the Space Com. Science 1.1
    class_space_id = room_map.get("Com. Science 1.1")
    if not class_space_id:
        print("Could not find space 'Com. Science 1.1', checking if it is already named 'Comp. Science 1.1'")
        class_space_id = room_map.get("Comp. Science 1.1")
        
    if not class_space_id:
        print("Error: Could not find Class Space.")
        return
        
    # Promote demo_creator to admin in the Class Space
    make_user_room_admin(admin_token, class_space_id, "@demo_creator:localhost")
        
    # Impersonate `@demo_creator:localhost` to do the renaming/linking
    impersonate_url = f"{HOMESERVER}/_synapse/admin/v1/users/@demo_creator:localhost/login"
    impersonate_res = make_request(impersonate_url, data={}, headers=headers, method='POST')
    creator_token = impersonate_res["access_token"]
    
    # 2. Rename Com. Science 1.1 -> Comp. Science 1.1
    rename_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{class_space_id}/state/m.room.name/"
    make_request(rename_url, data={"name": "Comp. Science 1.1"}, headers={"Authorization": f"Bearer {creator_token}"}, method='PUT')
    print("Renamed space to Comp. Science 1.1")
    
    # Rename Com. Science 1.1 News -> Comp. Science 1.1 News
    news_room_id = room_map.get("Com. Science 1.1 News")
    if not news_room_id:
        news_room_id = room_map.get("Comp. Science 1.1 News")
    if news_room_id:
        make_user_room_admin(admin_token, news_room_id, "@demo_creator:localhost")
        make_request(f"{HOMESERVER}/_matrix/client/v3/rooms/{news_room_id}/state/m.room.name/", data={"name": "Comp. Science 1.1 News"}, headers={"Authorization": f"Bearer {creator_token}"}, method='PUT')
        print("Renamed News channel to Comp. Science 1.1 News")
        
    # Rename Com. Science 1.1 Forum -> Comp. Science 1.1 Forum
    forum_room_id = room_map.get("Com. Science 1.1 Forum")
    if not forum_room_id:
        forum_room_id = room_map.get("Comp. Science 1.1 Forum")
    if forum_room_id:
        make_user_room_admin(admin_token, forum_room_id, "@demo_creator:localhost")
        make_request(f"{HOMESERVER}/_matrix/client/v3/rooms/{forum_room_id}/state/m.room.name/", data={"name": "Comp. Science 1.1 Forum"}, headers={"Authorization": f"Bearer {creator_token}"}, method='PUT')
        print("Renamed Forum channel to Comp. Science 1.1 Forum")
        
    # 3. Add groups/rooms as children of Class Space
    rooms_to_link = ["CS Demo Group Project", "Unit: Business Entrepreneurship"]
    for name in rooms_to_link:
        r_id = room_map.get(name)
        if r_id:
            # Promote demo_creator to admin in the child room
            make_user_room_admin(admin_token, r_id, "@demo_creator:localhost")
            
            # Link room as child of Comp. Science 1.1
            child_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{class_space_id}/state/m.space.child/{r_id}"
            make_request(child_url, data={"via": [SERVER_NAME], "suggested": False}, headers={"Authorization": f"Bearer {creator_token}"}, method='PUT')
            
            # Link back parent
            parent_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{r_id}/state/m.space.parent/{class_space_id}"
            make_request(parent_url, data={"via": [SERVER_NAME], "canonical": True}, headers={"Authorization": f"Bearer {creator_token}"}, method='PUT')
            print(f"Linked {name} to Comp. Science 1.1")
        else:
            print(f"Could not find room: {name}")

if __name__ == "__main__":
    main()
