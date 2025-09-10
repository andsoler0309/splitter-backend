"""
Example usage of the Splitter API
"""
import asyncio
import httpx
import json
import time

API_BASE_URL = "http://localhost:8000"

async def example_usage():
    """Example of how to use the Splitter API"""
    
    async with httpx.AsyncClient(timeout=600.0) as client:
        # 1. Check if API is running
        print("🔍 Checking API health...")
        health_response = await client.get(f"{API_BASE_URL}/")
        print(f"Health check: {health_response.json()}")
        
        if health_response.status_code != 200:
            print("❌ API is not running. Please start it first.")
            return
        
        # 2. Submit a separation job
        print("\n🎵 Submitting separation job...")
        
        # Example YouTube URL (replace with actual URL for testing)
        split_request = {
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "stems": ["bass", "drums", "vocals"]
        }
        
        print(f"Request: {json.dumps(split_request, indent=2)}")
        
        try:
            split_response = await client.post(
                f"{API_BASE_URL}/api/split",
                json=split_request
            )
            
            if split_response.status_code == 200:
                result = split_response.json()
                print(f"\n✅ Success! Job ID: {result['job_id']}")
                print(f"Status: {result['status']}")
                print(f"Message: {result['message']}")
                
                # 3. Download the separated stems
                print("\n⬇️  Download URLs:")
                for stem, url in result['download_urls'].items():
                    print(f"  {stem}: {API_BASE_URL}{url}")
                    
                # Example: Download one of the stems
                if result['download_urls']:
                    first_stem = list(result['download_urls'].keys())[0]
                    download_url = result['download_urls'][first_stem]
                    
                    print(f"\n📁 Downloading {first_stem} stem...")
                    download_response = await client.get(f"{API_BASE_URL}{download_url}")
                    
                    if download_response.status_code == 200:
                        filename = f"example_{first_stem}.wav"
                        with open(filename, "wb") as f:
                            f.write(download_response.content)
                        print(f"✅ Downloaded to: {filename}")
                    else:
                        print(f"❌ Download failed: {download_response.status_code}")
                        
            else:
                print(f"❌ Split request failed: {split_response.status_code}")
                print(f"Error: {split_response.text}")
                
        except httpx.TimeoutException:
            print("⏰ Request timed out. This is normal for long videos.")
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    print("🎵 Splitter API Example Usage")
    print("=" * 40)
    
    print("\n⚠️  Note: Make sure the API is running first:")
    print("   uvicorn main:app --reload")
    print("   or")
    print("   docker-compose up")
    
    print("\n🚀 Starting example...")
    asyncio.run(example_usage())
