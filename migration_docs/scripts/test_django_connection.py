#!/usr/bin/env python3
"""
Test Django connection to CockroachDB.
Verifies that Django can connect and perform basic operations.
"""

import os
import sys
import django
from pathlib import Path

# Add scheduler directory to path
scheduler_dir = Path(__file__).parent.parent.parent / 'scheduler'
sys.path.insert(0, str(scheduler_dir))

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scheduler.settings')

# Setup Django
django.setup()

from django.db import connection
from django.core.management import execute_from_command_line
from profiles.models import User
from providers.models import Job

def test_connection():
    """Test basic database connection."""
    print("Testing Django connection to CockroachDB...")
    print()
    
    try:
        # Test connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT version();")
            version = cursor.fetchone()[0]
            print(f"✅ Database connection successful")
            print(f"   Version: {version[:100]}...")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    
    return True

def test_orm_operations():
    """Test basic ORM operations."""
    print()
    print("Testing ORM operations...")
    
    try:
        # Test query
        user_count = User.objects.count()
        print(f"✅ User count query: {user_count} users")
        
        # Test job count
        job_count = Job.objects.count()
        print(f"✅ Job count query: {job_count} jobs")
        
        # Test create (if we have a test user)
        if user_count > 0:
            first_user = User.objects.first()
            print(f"✅ User retrieval: {first_user.user_id}")
        
        return True
    except Exception as e:
        print(f"❌ ORM operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_migrations():
    """Check if migrations are needed."""
    print()
    print("Checking migrations...")
    
    try:
        # Check for pending migrations
        from django.core.management import call_command
        from io import StringIO
        
        out = StringIO()
        call_command('showmigrations', '--plan', stdout=out)
        output = out.getvalue()
        
        if '[ ]' in output:
            print("⚠️  Pending migrations detected:")
            for line in output.split('\n'):
                if '[ ]' in line:
                    print(f"   {line.strip()}")
        else:
            print("✅ No pending migrations")
        
        return True
    except Exception as e:
        print(f"⚠️  Could not check migrations: {e}")
        return True  # Don't fail on this

def main():
    print("=" * 60)
    print("Django CockroachDB Connection Test")
    print("=" * 60)
    print()
    
    # Test connection
    if not test_connection():
        sys.exit(1)
    
    # Test ORM
    if not test_orm_operations():
        sys.exit(1)
    
    # Check migrations
    test_migrations()
    
    print()
    print("=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)

if __name__ == '__main__':
    main()
