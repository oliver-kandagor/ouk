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
    
    # Fetch nonce
    req = urllib.request.Request(admin_api_url, method='GET')
    try:
        with urllib.request.urlopen(req) as resp:
            nonce = json.loads(resp.read().decode('utf-8'))['nonce']
    except Exception as e:
        print(f"Failed to fetch nonce: {e}")
        return None
        
    admin_str = "admin" if admin else "notadmin"
    mac = hmac.new(key=SHARED_SECRET.encode('utf-8'), digestmod=hashlib.sha1)
    mac.update(nonce.encode('utf-8') + b"\x00" + username.encode('utf-8') + b"\x00" + b"user" + b"\x00" + admin_str.encode('utf-8'))
    
    payload = {
        "nonce": nonce,
        "username": username,
        "password": "user",
        "admin": admin,
        "mac": mac.hexdigest()
    }
    
    res = make_request(admin_api_url, data=payload)
    if res and "access_token" in res:
        token = res["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        disp_url = f"{HOMESERVER}/_matrix/client/v3/profile/{user_id}/displayname"
        make_request(disp_url, data={"displayname": displayname}, headers=headers, method='PUT')
        return {"user_id": user_id, "token": token}
    else:
        if creator_token:
            admin_login_url = f"{HOMESERVER}/_synapse/admin/v1/users/{user_id}/login"
            headers = {"Authorization": f"Bearer {creator_token}"}
            login_res = make_request(admin_login_url, data={}, headers=headers, method='POST')
            if login_res and "access_token" in login_res:
                return {"user_id": user_id, "token": login_res["access_token"]}
    return None

def create_room(token, name, topic, is_space=False, is_announcement=False):
    url = f"{HOMESERVER}/_matrix/client/v3/createRoom"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "name": name,
        "topic": topic,
        "preset": "public_chat",
        "visibility": "public"
    }
    if is_space:
        payload["creation_content"] = {"type": "m.space"}
    if is_announcement:
        payload["power_level_content_override"] = {
            "events_default": 50,
            "users_default": 0,
            "state_default": 100
        }
    res = make_request(url, data=payload, headers=headers)
    return res.get("room_id") if res else None

def add_room_to_space(token, space_id, room_id):
    headers = {"Authorization": f"Bearer {token}"}
    child_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{space_id}/state/m.space.child/{room_id}"
    make_request(child_url, data={"via": [SERVER_NAME], "suggested": False}, headers=headers, method='PUT')
    parent_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.space.parent/{space_id}"
    make_request(parent_url, data={"via": [SERVER_NAME], "canonical": True}, headers=headers, method='PUT')

def join_user_to_room(user_token, room_id):
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/join"
    headers = {"Authorization": f"Bearer {user_token}"}
    make_request(url, data={}, headers=headers)

def set_user_power_levels(token, room_id, users_levels, events_default=0):
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.room.power_levels"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "users": users_levels,
        "users_default": 0,
        "events": {
            "m.room.name": 50,
            "m.room.power_levels": 100,
            "m.room.history_visibility": 100,
            "m.room.canonical_alias": 50,
            "m.room.avatar": 50,
            "m.room.tombstone": 100,
            "m.room.server_acl": 100,
            "m.room.encryption": 100
        },
        "events_default": events_default,
        "state_default": 50,
        "notifications": {"room": 20}
    }
    make_request(url, data=payload, headers=headers, method='PUT')

def main():
    admin_uname = f"class_admin_{int(time.time())}"
    print(f"Registering unique admin: {admin_uname}...")
    creator = register_user(admin_uname, "Class Creation Admin", admin=True)
    if not creator:
        print("Failed to authenticate creator admin.")
        return
        
    # Get all rooms to find the main CS Space ID
    rooms_url = f"{HOMESERVER}/_synapse/admin/v1/rooms"
    headers = {"Authorization": f"Bearer {creator['token']}"}
    rooms_res = make_request(rooms_url, headers=headers, method='GET')
    
    room_map = {}
    if rooms_res and "rooms" in rooms_res:
        room_map = {r["name"]: r["room_id"] for r in rooms_res["rooms"] if "name" in r and r["name"]}
    
    cs_dept_space_id = room_map.get("Computer Science Department")
    print(f"Main CS Space ID: {cs_dept_space_id}")
    
    # 1. Create Space: Com. Science 1.1
    class_space_id = create_room(creator["token"], "Com. Science 1.1", "Year 1 Semester 1 Computer Science Space", is_space=True)
    print(f"Created Class Space: {class_space_id}")
    
    if cs_dept_space_id and class_space_id:
        # Link Class Space under CS Department Space
        add_room_to_space(creator["token"], cs_dept_space_id, class_space_id)
        print("Linked class space under CS Department space.")
        
    # 2. Create Rooms inside Com. Science 1.1
    news_room_id = create_room(creator["token"], "Com. Science 1.1 News", "Official Class Notices & news (Only Admin/Rep can speak)", is_announcement=True)
    forum_room_id = create_room(creator["token"], "Com. Science 1.1 Forum", "Discussion group for Com. Science 1.1", is_announcement=False)
    
    print(f"Created News Room: {news_room_id}")
    print(f"Created Forum Room: {forum_room_id}")
    
    if class_space_id:
        add_room_to_space(creator["token"], class_space_id, news_room_id)
        add_room_to_space(creator["token"], class_space_id, forum_room_id)
        
    # Get tokens of members
    cs_student_1 = register_user("cs_student_1", "CS Student 1 (Class Rep)", creator_token=creator["token"])
    group_bot = register_user("group_bot", "Group Bot", creator_token=creator["token"])
    
    members = []
    # Join cs_student_1 (Class Rep)
    if cs_student_1:
        members.append(cs_student_1)
    if group_bot:
        members.append(group_bot)
        
    # Join a few other students to show community interaction
    for i in range(2, 8):
        u = register_user(f"cs_student_{i}", f"CS Student {i}", creator_token=creator["token"])
        if u:
            members.append(u)
            
    # Join lecturers
    cs_admin_1 = register_user("cs_admin_1", "Prof. Kamau (CS HOD)", admin=True, creator_token=creator["token"])
    cs_admin_2 = register_user("cs_admin_2", "Dr. Wanjiku (CS Lecturer)", admin=True, creator_token=creator["token"])
    if cs_admin_1:
        members.append(cs_admin_1)
    if cs_admin_2:
        members.append(cs_admin_2)
        
    # Join all to space and rooms
    for m in members:
        if class_space_id:
            join_user_to_room(m["token"], class_space_id)
        if news_room_id:
            join_user_to_room(m["token"], news_room_id)
        if forum_room_id:
            join_user_to_room(m["token"], forum_room_id)
            
    # Set CS Student 1 as the Class Rep (Admin, Power level 100)
    # Set CS HOD and Lecturer to 100 too
    levels = {
        cs_student_1["user_id"]: 100,
        creator["user_id"]: 100
    }
    if cs_admin_1:
        levels[cs_admin_1["user_id"]] = 100
    if cs_admin_2:
        levels[cs_admin_2["user_id"]] = 100
        
    # Set levels on Space
    if class_space_id:
        set_user_power_levels(creator["token"], class_space_id, levels, events_default=0)
    # Set levels on News (only admin/rep can post, events_default=50)
    if news_room_id:
        set_user_power_levels(creator["token"], news_room_id, levels, events_default=50)
    # Set levels on Forum (everyone can post, events_default=0)
    if forum_room_id:
        set_user_power_levels(creator["token"], forum_room_id, levels, events_default=0)
        
    # Set cs_student_1 display name to highlight they are Class Rep
    headers = {"Authorization": f"Bearer {cs_student_1['token']}"}
    disp_url = f"{HOMESERVER}/_matrix/client/v3/profile/{cs_student_1['user_id']}/displayname"
    make_request(disp_url, data={"displayname": "Otieno (CS 1.1 Class Rep)"}, headers=headers, method='PUT')
    
    print("Class setup finished successfully!")

if __name__ == "__main__":
    main()
