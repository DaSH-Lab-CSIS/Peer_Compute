#!/usr/bin/env python3
"""
Diagnostic script to check cache_dir permissions and identify issues.
Run this on colva4 to diagnose the readonly database issue.
"""
import os
import stat
import sys
from pathlib import Path

def check_permissions(path, name):
    """Check and display permissions for a path."""
    if not os.path.exists(path):
        print(f"❌ {name}: DOES NOT EXIST")
        return False
    
    try:
        stat_info = os.stat(path)
        mode = stat_info.st_mode
        permissions = stat.filemode(mode)
        uid = stat_info.st_uid
        gid = stat_info.st_gid
        
        # Get current user info
        current_uid = os.getuid()
        current_gid = os.getgid()
        
        # Check if writable
        is_writable = os.access(path, os.W_OK)
        is_readable = os.access(path, os.R_OK)
        
        print(f"\n{name}: {path}")
        print(f"  Permissions: {permissions}")
        print(f"  Owner UID: {uid} (current: {current_uid})")
        print(f"  Owner GID: {gid} (current: {current_gid})")
        print(f"  Readable: {is_readable}")
        print(f"  Writable: {is_writable}")
        
        if not is_writable:
            print(f"  ⚠️  WARNING: Not writable by current user!")
            if uid != current_uid:
                print(f"  ⚠️  Owner mismatch: file owned by UID {uid}, current user is UID {current_uid}")
        
        return is_writable
    except Exception as e:
        print(f"❌ Error checking {name}: {e}")
        return False

def main():
    print("=" * 60)
    print("Cache Directory Permissions Diagnostic")
    print("=" * 60)
    
    # Get current working directory
    cwd = os.getcwd()
    print(f"\nCurrent working directory: {cwd}")
    print(f"Current user: {os.getenv('USER', 'unknown')}")
    print(f"Current UID: {os.getuid()}")
    print(f"Current GID: {os.getgid()}")
    
    # Check parent directory
    parent_dir = cwd
    print("\n" + "=" * 60)
    parent_ok = check_permissions(parent_dir, "Parent directory")
    
    # Check cache_dir
    cache_dir = os.path.join(cwd, "cache_dir")
    print("\n" + "=" * 60)
    cache_dir_ok = check_permissions(cache_dir, "cache_dir directory")
    
    # Check files inside cache_dir
    if os.path.exists(cache_dir) and os.path.isdir(cache_dir):
        print("\n" + "=" * 60)
        print("Files inside cache_dir:")
        try:
            files = os.listdir(cache_dir)
            if files:
                for file in files:
                    file_path = os.path.join(cache_dir, file)
                    check_permissions(file_path, f"  {file}")
            else:
                print("  (empty directory)")
        except Exception as e:
            print(f"  ❌ Error listing files: {e}")
    
    # Check cached_images
    cached_images = os.path.join(cwd, "cached_images")
    print("\n" + "=" * 60)
    cached_images_ok = check_permissions(cached_images, "cached_images directory")
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    print("=" * 60)
    if not parent_ok:
        print("❌ Parent directory is not writable")
    if not cache_dir_ok:
        print("❌ cache_dir is not writable - THIS IS LIKELY THE PROBLEM")
    if not cached_images_ok:
        print("⚠️  cached_images is not writable")
    
    if cache_dir_ok and parent_ok:
        print("✅ All directories appear to have correct permissions")
        print("\nIf you're still getting errors, try:")
        print("  rm -rf cache_dir")
        print("  python provider/provider1.py <user_id>")

if __name__ == "__main__":
    main()



