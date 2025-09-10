#!/usr/bin/env python3
"""
Simple test to debug the opts issue
"""
import os
import sys
sys.path.append('/app')

from services.youtube_service import YouTubeService

def test_opts_issue():
    """Test to see what's wrong with the opts parameter"""
    print("🔍 Testing opts parameter issue...")
    
    youtube_service = YouTubeService()
    
    # Check the initial ydl_opts
    print(f"ydl_opts type: {type(youtube_service.ydl_opts)}")
    print(f"ydl_opts keys: {list(youtube_service.ydl_opts.keys())}")
    print(f"outtmpl value: {youtube_service.ydl_opts.get('outtmpl')}")
    print(f"outtmpl type: {type(youtube_service.ydl_opts.get('outtmpl'))}")
    
    # Test copying and modifying
    output_dir = "/tmp/test"
    opts = youtube_service.ydl_opts.copy()
    print(f"\nAfter copy - opts type: {type(opts)}")
    
    # Test the path join operation
    try:
        new_outtmpl = os.path.join(output_dir, '%(title)s.%(ext)s')
        print(f"new_outtmpl: {new_outtmpl} (type: {type(new_outtmpl)})")
        opts['outtmpl'] = new_outtmpl
        print(f"After assignment - outtmpl: {opts['outtmpl']} (type: {type(opts['outtmpl'])})")
    except Exception as e:
        print(f"Error during path join: {e}")
    
    # Test dirname operation
    try:
        dirname_result = os.path.dirname(opts['outtmpl'])
        print(f"dirname result: {dirname_result}")
    except Exception as e:
        print(f"Error during dirname: {e}")

if __name__ == "__main__":
    test_opts_issue()
