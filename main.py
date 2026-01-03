import os
import uvicorn
import requests
import yt_dlp
import subprocess
from fastapi import FastAPI, BackgroundTasks
from pymongo import MongoClient

# --- CONFIG ---
app = FastAPI(title="Sudeep Music API v2.5", description="Smart Background Mode (Fix Loops)")

# MongoDB Connect
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("⚠️ WARNING: MONGO_URL nahi mila! Config check kar.")

try:
    client = MongoClient(MONGO_URL)
    db = client["MusicAPI_DB"]
    cache_col = db["songs_cache"]
    print("✅ MongoDB Connected!")
except Exception as e:
    print(f"❌ DB Error: {e}")

# Catbox API
CATBOX_URL = "https://catbox.moe/user/api.php"

# --- SYSTEM CHECK ---
@app.on_event("startup")
async def check_dependencies():
    print("\n" + "="*40)
    print("🚀 STARTING SMART MODE...")
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("✅ FFmpeg Running!")
    except:
        print("❌ CRITICAL: FFmpeg missing!")
    
    if os.path.exists("cookies.txt"):
        print("✅ Cookies Found! (Using Premium)")
    else:
        print("⚠️ Cookies Not Found! (Using Public)")
    print("="*40 + "\n")

# --- BACKGROUND TASK FUNCTION ---
def process_background_download(video_id, title, thumbnail, channel):
    print(f"⏳ Background Task Started: {title}")
    
    file_name = f"{video_id}.mp3"
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

    # Settings: Cookies agar hain to use hongi
    ydl_opts_down = {
        'format': 'bestaudio/best',
        'outtmpl': file_name,
        'quiet': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0',
        'cookiefile': cookie_file, # ✅ Cookies Auto-Detect
        'cachedir': False,
        'check_formats': False,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '64', # Speed ke liye 64kbps
        }],
    }

    try:
        # 1. Download
        with yt_dlp.YoutubeDL(ydl_opts_down) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        
        if not os.path.exists(file_name):
            raise Exception("Download failed (File not found)")

        # 2. Upload
        print("☁️ Uploading to Catbox...")
        data = {"reqtype": "fileupload", "userhash": ""}
        catbox_link = None
        
        with open(file_name, "rb") as f:
            files = {"fileToUpload": f}
            response = requests.post(CATBOX_URL, data=data, files=files)
            if response.status_code == 200 and "catbox.moe" in response.text:
                catbox_link = response.text.strip()
        
        # Cleanup
        if os.path.exists(file_name): os.remove(file_name)

        if not catbox_link:
            raise Exception("Catbox upload failed")

        # 3. SUCCESS UPDATE
        cache_col.update_one(
            {"video_id": video_id},
            {"$set": {
                "status": "completed",
                "catbox_link": catbox_link,
                "created_at": "v2.5 Smart"
            }}
        )
        print(f"✅ DONE: {title}")

    except Exception as e:
        print(f"❌ ERROR in Background: {e}")
        if os.path.exists(file_name): os.remove(file_name)
        
        # 🔥 ERROR UPDATE (Delete nahi karenge, Failed mark karenge)
        cache_col.update_one(
            {"video_id": video_id},
            {"$set": {"status": "failed", "error_msg": str(e)}}
        )

# --- API ENDPOINT ---
@app.get("/")
def home():
    return {"status": "Running", "mode": "Smart State (Cookies Auto)", "version": "2.5"}

@app.get("/play")
async def play_song(query: str, background_tasks: BackgroundTasks):
    
    print(f"🔎 Searching: {query}")
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

    # 1. SEARCH
    ydl_opts_search = {
        'quiet': True, 'noplaylist': True, 
        'check_formats': False, 'cachedir': False, 'cookiefile': cookie_file
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            if "http" in query:
                info = ydl.extract_info(query, download=False)
            else:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            
            video_id = info['id']
            title = info['title']
            duration = info.get('duration_string', 'Unknown')
            thumbnail = info.get('thumbnail')
            channel = info.get('uploader')
            
    except Exception as e:
        return {"status": "error", "message": f"Song nahi mila: {str(e)}"}

    # 2. SMART CACHE CHECK 🧠
    cached_song = cache_col.find_one({"video_id": video_id})
    
    # CASE A: Song Completed
    if cached_song and cached_song.get("status") == "completed":
        print(f"🚀 Cache Hit: {title}")
        return {
            "status": "success",
            "source": "database",
            "title": cached_song['title'],
            "url": cached_song['catbox_link'],
            "thumbnail": cached_song.get('thumbnail', thumbnail),
            "duration": duration,
            "video_id": video_id
        }
    
    # CASE B: Processing
    if cached_song and cached_song.get("status") == "processing":
        return {
            "status": "processing",
            "message": "Song download ho raha hai, bas thoda wait...",
            "eta": "15 seconds"
        }
        
    # CASE C: Failed (Retry Logic)
    if cached_song and cached_song.get("status") == "failed":
        print(f"⚠️ Retrying Failed Song: {title}")
        # Status wapas processing karo aur task start karo
        cache_col.update_one({"video_id": video_id}, {"$set": {"status": "processing"}})
        background_tasks.add_task(process_background_download, video_id, title, thumbnail, channel)
        return {
            "status": "processing",
            "message": "Pichli baar fail hua tha, dubara try kar rahe hain. 30s rukna.",
            "error_was": cached_song.get("error_msg")
        }

    # CASE D: New Song
    print(f"🆕 New Task: {title}")
    
    # DB mein 'processing' daalo
    cache_col.insert_one({
        "video_id": video_id,
        "title": title,
        "thumbnail": thumbnail,
        "channel": channel,
        "status": "processing",
        "catbox_link": None
    })
    
    background_tasks.add_task(process_background_download, video_id, title, thumbnail, channel)

    return {
        "status": "processing",
        "message": "Background process started. Ask again in 30 seconds.",
        "title": title,
        "eta": "30 seconds"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
