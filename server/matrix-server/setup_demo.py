import hmac
import hashlib
import json
import urllib.request
import urllib.error
import time

HOMESERVER = "http://localhost:8008"
SHARED_SECRET = "zUu&~T_.kV^83gU4#faW:U7*#p8Mt,yVJGDRJ4A;0Mm74-:#Ew"
SERVER_NAME = "localhost"

# Helper function to send requests with automatic retry on 429 rate limits
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

# Register user via shared secret
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
    mac.update(b"user") # Password is 'user' as requested
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
        # Set display name
        headers = {"Authorization": f"Bearer {token}"}
        disp_url = f"{HOMESERVER}/_matrix/client/v3/profile/{user_id}/displayname"
        make_request(disp_url, data={"displayname": displayname}, headers=headers, method='PUT')
        print(f"Registered user: {user_id} ({displayname})")
        return {"user_id": user_id, "token": token}
    else:
        # User might already exist, let's try logging in
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
            print(f"User {username} already exists, logged in.")
            return {"user_id": login_res["user_id"], "token": login_res["access_token"]}
        else:
            print(f"Failed to register/login user {username}: {res}")
            return None

# Create room (or space)
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
        payload["preset"] = "public_chat" # Make public so demo users can join
    
    if is_announcement:
        # Override power levels so only power level >= 50 can send messages
        payload["power_level_content_override"] = {
            "events_default": 50, # Moderators can send messages, students can't
            "users_default": 0,
            "state_default": 100
        }
        
    res = make_request(url, data=payload, headers=headers)
    if res and "room_id" in res:
        print(f"Created {'Space' if is_space else 'Room'}: {name} ({res['room_id']})")
        return res["room_id"]
    return None

# Add room to space
def add_room_to_space(token, space_id, room_id):
    if not space_id or not room_id:
        print("Invalid space_id or room_id, skipping link.")
        return
        
    headers = {"Authorization": f"Bearer {token}"}
    # 1. State event m.space.child on the Space
    child_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{space_id}/state/m.space.child/{room_id}"
    make_request(child_url, data={"via": [SERVER_NAME], "suggested": False}, headers=headers, method='PUT')
    
    # 2. State event m.space.parent on the Child Room
    parent_url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.space.parent/{space_id}"
    make_request(parent_url, data={"via": [SERVER_NAME], "canonical": True}, headers=headers, method='PUT')
    print(f"Linked room {room_id} to space {space_id}")

# Join user to room
def join_user_to_room(user_token, room_id):
    if not room_id:
        return
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/join"
    headers = {"Authorization": f"Bearer {user_token}"}
    make_request(url, data={}, headers=headers)

# Set user power levels in a room
def set_user_power_levels(creator_token, room_id, users_levels, events_default=0):
    if not room_id:
        return
    url = f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/state/m.room.power_levels"
    headers = {"Authorization": f"Bearer {creator_token}"}
    
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
        "notifications": {
            "room": 20
        }
    }
    make_request(url, data=payload, headers=headers, method='PUT')

def main():
    print("Starting OUK Demo setup...")
    
    # 1. Register demo creator admin
    creator = register_user("demo_creator", "OUK System Admin", admin=True)
    if not creator:
        print("Failed to register demo creator.")
        return
    
    # 2. Register CS Course Users (2 Admins, 4 Mods, 10 Students)
    cs_users = []
    # Admins
    cs_users.append(register_user("cs_admin_1", "Prof. Kamau (CS HOD)", admin=True))
    cs_users.append(register_user("cs_admin_2", "Dr. Wanjiku (CS Lecturer)", admin=True))
    # Mods
    cs_users.append(register_user("cs_mod_1", "Otieno (CS Class Rep)"))
    cs_users.append(register_user("cs_mod_2", "Amina (CS Moderator)"))
    cs_users.append(register_user("cs_mod_3", "Kiprotich (CS Moderator)"))
    cs_users.append(register_user("cs_mod_4", "Mwangi (CS Moderator)"))
    # Students
    for i in range(1, 11):
        cs_users.append(register_user(f"cs_student_{i}", f"CS Student {i}"))
        
    # Filter out None users
    cs_users = [u for u in cs_users if u is not None]
    
    # 3. Register Math & Computing Course Users (2 Admins, 4 Mods, 10 Students)
    math_users = []
    # Admins
    math_users.append(register_user("math_admin_1", "Prof. Nduta (Math HOD)", admin=True))
    math_users.append(register_user("math_admin_2", "Dr. Ochieng (Math Lecturer)", admin=True))
    # Mods
    math_users.append(register_user("math_mod_1", "Chebet (Math Class Rep)"))
    math_users.append(register_user("math_mod_2", "Math Mod 2"))
    math_users.append(register_user("math_mod_3", "Math Mod 3"))
    math_users.append(register_user("math_mod_4", "Math Mod 4"))
    # Students
    for i in range(1, 11):
        math_users.append(register_user(f"math_student_{i}", f"Math Student {i}"))
        
    # Filter out None users
    math_users = [u for u in math_users if u is not None]
    
    # Combined users list
    all_users = cs_users + math_users + [creator]
    
    # Power levels for CS announcements room
    cs_levels = {
        cs_users[0]["user_id"]: 100, # CS Admin 1
        cs_users[1]["user_id"]: 100, # CS Admin 2
        cs_users[2]["user_id"]: 50,  # CS Class Rep
        cs_users[3]["user_id"]: 50,  # CS Mod 2
        cs_users[4]["user_id"]: 50,  # CS Mod 3
        cs_users[5]["user_id"]: 50,  # CS Mod 4
        creator["user_id"]: 100      # Creator
    }
    
    # 4. Create Computer Science Space
    cs_space = create_room(creator["token"], "Computer Science Department", "Space for CS Students and Lecturers", is_space=True)
    
    # Channels under CS Space
    cs_notices = create_room(creator["token"], "CS Notices & Announcements", "Official announcements (Only Admins/Class Rep can chat)", is_announcement=True)
    cs_forum = create_room(creator["token"], "CS Discussion Forum", "General chat for CS students", is_announcement=False)
    cs_qa = create_room(creator["token"], "Programming Q&A", "Ask questions and get answers about programming", is_announcement=False)
    cs_demo_group = create_room(creator["token"], "CS Demo Group Project", "At least 4 members group for projects", is_announcement=False)
    
    # Link channels to CS Space
    add_room_to_space(creator["token"], cs_space, cs_notices)
    add_room_to_space(creator["token"], cs_space, cs_forum)
    add_room_to_space(creator["token"], cs_space, cs_qa)
    add_room_to_space(creator["token"], cs_space, cs_demo_group)
    
    # Join CS users to Space and Channels
    for u in cs_users:
        join_user_to_room(u["token"], cs_space)
        join_user_to_room(u["token"], cs_notices)
        join_user_to_room(u["token"], cs_forum)
        join_user_to_room(u["token"], cs_qa)
        
    # Configure power levels in CS Notices so only CS Admins and Class Rep can send messages
    set_user_power_levels(creator["token"], cs_notices, cs_levels, events_default=50)
    
    # Join selected members to CS Demo Group (4 members)
    for i in range(6, 10): # cs_student_1 to cs_student_4 correspond to index 6 to 9 in cs_users
        join_user_to_room(cs_users[i]["token"], cs_demo_group)
        
    print("CS Department Space and Rooms setup completed.")

    # 5. Create Business Entrepreneurship Shared Unit Channel
    # This channel is shared between CS (Mathematics & Computing) and Business/Economics courses
    shared_unit = create_room(creator["token"], "Unit: Business Entrepreneurship", "Shared Unit Group for Computing and Business Students", is_announcement=False)
    
    # Link to CS Space
    add_room_to_space(creator["token"], cs_space, shared_unit)
    
    # Join ALL CS and Math users to the shared unit
    for u in cs_users + math_users:
        join_user_to_room(u["token"], shared_unit)
        
    print("Shared Unit setup completed.")

    # 6. Create Clubs & Societies Space
    clubs_space = create_room(creator["token"], "Clubs & Societies Space", "Space for varsity clubs and social interaction", is_space=True)
    
    clubs_main = create_room(creator["token"], "Clubs Announcements", "Official updates from the Dean (Only Admins can chat)", is_announcement=True)
    tech_club = create_room(creator["token"], "Tech & Coding Club", "For software devs and hardware geeks", is_announcement=False)
    drama_club = create_room(creator["token"], "Drama & Art Club", "Acting, poetry, and fine arts", is_announcement=False)
    sports_club = create_room(creator["token"], "Sports & Athletics Club", "Football, rugby, basketball, and athletics", is_announcement=False)
    
    # Link clubs to space
    add_room_to_space(creator["token"], clubs_space, clubs_main)
    add_room_to_space(creator["token"], clubs_space, tech_club)
    add_room_to_space(creator["token"], clubs_space, drama_club)
    add_room_to_space(creator["token"], clubs_space, sports_club)
    
    # Join all users to clubs space and main channel
    for u in cs_users + math_users:
        join_user_to_room(u["token"], clubs_space)
        join_user_to_room(u["token"], clubs_main)
        
    # Join CS users to Tech Club
    for u in cs_users:
        join_user_to_room(u["token"], tech_club)
        
    # Join subset to Drama Club
    for u in cs_users[6:10] + math_users[6:10]:
        join_user_to_room(u["token"], drama_club)
        
    # Join subset to Sports Club
    for u in cs_users[10:14] + math_users[10:14]:
        join_user_to_room(u["token"], sports_club)
        
    print("Clubs & Societies Space setup completed.")

    # 7. Create Student Communities Space (Religious/Interest Groups)
    comm_space = create_room(creator["token"], "Student Communities", "Diverse religious and social groups", is_space=True)
    
    comm_main = create_room(creator["token"], "Communities Notices", "Dean of Students announcements (Only Admins can chat)", is_announcement=True)
    christian_union = create_room(creator["token"], "Christian Union (CU)", "Christian fellowship and events", is_announcement=False)
    catholic_assoc = create_room(creator["token"], "Catholic Students Association", "Catholic liturgy, meetings and fellowship", is_announcement=False)
    muslim_assoc = create_room(creator["token"], "Muslim Students Association", "Islamic society lectures, events and prayers", is_announcement=False)
    
    # Link to space
    add_room_to_space(creator["token"], comm_space, comm_main)
    add_room_to_space(creator["token"], comm_space, christian_union)
    add_room_to_space(creator["token"], comm_space, catholic_assoc)
    add_room_to_space(creator["token"], comm_space, muslim_assoc)
    
    # Join all to Space and Main
    for u in cs_users + math_users:
        join_user_to_room(u["token"], comm_space)
        join_user_to_room(u["token"], comm_main)
        
    # Populate communities with subset of students
    for idx, u in enumerate(cs_users[6:] + math_users[6:]):
        if idx % 3 == 0:
            join_user_to_room(u["token"], christian_union)
        elif idx % 3 == 1:
            join_user_to_room(u["token"], catholic_assoc)
        else:
            join_user_to_room(u["token"], muslim_assoc)
            
    print("Student Communities Space setup completed.")

    # 8. Create All OUK Students Space (Campus-wide)
    all_students_space = create_room(creator["token"], "All OUK Students Community", "Campus-wide communications", is_space=True)
    
    all_announcements = create_room(creator["token"], "OUK Announcements", "Official varsity news (Only Admins can chat)", is_announcement=True)
    general_qa = create_room(creator["token"], "General Q&A Portal", "Ask any question about OUK administration", is_announcement=False)
    
    # Link to space
    add_room_to_space(creator["token"], all_students_space, all_announcements)
    add_room_to_space(creator["token"], all_students_space, general_qa)
    
    # Join all users
    for u in cs_users + math_users:
        join_user_to_room(u["token"], all_students_space)
        join_user_to_room(u["token"], all_announcements)
        join_user_to_room(u["token"], general_qa)
        
    print("Campus-wide OUK Space setup completed.")
    print("OUK Demo Setup finished successfully!")

if __name__ == "__main__":
    main()
