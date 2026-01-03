import os
import uvicorn
import requests
import yt_dlp
import subprocess
from fastapi import FastAPI, BackgroundTasks
from pymongo import MongoClient

# --- CONFIG ---
app = FastAPI(title="Sudeep Music API v2.5", description="Background Mode (Anti-Timeout)")

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
    print("🚀 STARTING BACKGROUND MODE...")
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("✅ FFmpeg Running!")
    except:
        print("❌ CRITICAL: FFmpeg missing!")
    
    if os.path.exists("cookies.txt"):
        print("✅ Cookies Found! (Premium Access)")
    else:
        print("⚠️ Cookies Not Found! (Public Mode)")
    print("="*40 + "\n")

# --- BACKGROUND TASK FUNCTION ---
# Ye function chupke se peeche chalega
def process_background_download(video_id, title, thumbnail, channel):
    print(f"⏳ Background Task Started: {title}")
    
    file_name = f"{video_id}.mp3"
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

    # 🔥 TURBO SETTINGS (Fast Download & Upload)
    ydl_opts_down = {
        'format': 'bestaudio/best',
        'outtmpl': file_name,
        'quiet': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0',
        'cookiefile': cookie_file,
        'cachedir': False,
        'check_formats': False,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '64', # 64kbps for Ultra Speed
        }],
    }

    try:
        # 1. Download
        with yt_dlp.YoutubeDL(ydl_opts_down) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        
        if not os.path.exists(file_name):
            print("❌ Download Failed in Background")
            return

        # 2. Upload to Catbox
        print("☁️ Uploading to Catbox...")
        data = {"reqtype": "fileupload", "userhash": ""}
        catbox_link = None
        
        with open(file_name, "rb") as f:
            files = {"fileToUpload": f}
            response = requests.post(CATBOX_URL, data=data, files=files)
            if response.status_code == 200 and "catbox.moe" in response.text:
                catbox_link = response.text.strip()
        
        # Cleanup
        if os.path.exists(file_name):
            os.remove(file_name)

        if not catbox_link:
            print("❌ Upload Failed")
            return

        # 3. Save to DB
        cache_col.insert_one({
            "video_id": video_id,
            "title": title,
            "catbox_link": catbox_link,
            "thumbnail": thumbnail,
            "channel": channel,
            "created_at": "v2.5 Background"
        })
        print(f"✅ Background Task Completed: {title}")

    except Exception as e:
        print(f"❌ Background Error: {e}")
        if os.path.exists(file_name): os.remove(file_name)

# --- API ENDPOINT ---
@app.get("/")
def home():
    return {"status": "Running", "mode": "Background Async", "version": "2.5"}

@app.get("/play")
async def play_song(query: str, background_tasks: BackgroundTasks):
    
    print(f"🔎 Searching: {query}")
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

    # 1. SEARCH ONLY (Fast)
    ydl_opts_search = {
        'quiet': True, 
        'noplaylist': True, 
        'check_formats': False,
        'cachedir': False,
        'cookiefile': cookie_file
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

    # 2. CACHE CHECK (Instant Result)
    cached_song = cache_col.find_one({"video_id": video_id})
    
    if cached_song:
        print(f"🚀 Cache Hit: {title}")
        return {
            "status": "success",
            "source": "database (Ultra Fast)",
            "title": cached_song['title'],
            "url": cached_song['catbox_link'],
            "thumbnail": cached_song.get('thumbnail', thumbnail),
            "duration": duration,
            "video_id": video_id
        }

    # 3. IF NOT FOUND -> START BACKGROUND TASK
    print(f"⚠️ Cache Miss. Starting Background Process for: {title}")
    
    # Ye line magic karegi: Function ko background mein daal degi
    background_tasks.add_task(process_background_download, video_id, title, thumbnail, channel)

    return {
        "status": "processing",
        "message": "Song processing started in background. Please ask again in 30 seconds.",
        "title": title,
        "eta": "30-60 seconds"
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
