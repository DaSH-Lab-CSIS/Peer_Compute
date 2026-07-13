import os
import sqlite3
import sys
import tempfile
import diskcache
import docker


# requires the image to be within memory limit.
# use self.cache.clear() to clear the diskCache.


def _default_cache_base():
    """User-writable cache root (avoids deploy-tree cache_dir owned by another user)."""
    override = os.environ.get("PROVIDER_CACHE_DIR", "").strip()
    if override:
        return os.path.abspath(override)
    xdg = os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache"
    )
    return os.path.join(xdg, "serverless_scheduler", "provider")


def _open_diskcache(directory):
    os.makedirs(directory, mode=0o755, exist_ok=True)
    try:
        return diskcache.Cache(directory)
    except sqlite3.OperationalError as exc:
        if "readonly" not in str(exc).lower():
            raise
        fallback = os.path.join(
            tempfile.gettempdir(),
            f"serverless_scheduler_provider_cache_{os.getuid()}",
            "diskcache",
        )
        os.makedirs(fallback, mode=0o755, exist_ok=True)
        print(
            f"Warning: diskcache directory is not writable ({directory}); "
            f"using {fallback}",
            file=sys.stderr,
        )
        return diskcache.Cache(fallback)


class HybridImageManager:
    def __init__(self, memory_limit, disk_limit):
        self.memory_limit = memory_limit
        self.disk_limit = disk_limit
        self.memory_cache = {}  # Dictionary to store images in memory
        self.docker_client = docker.from_env()
        cache_base = _default_cache_base()
        diskcache_dir = os.path.join(cache_base, "diskcache")
        self.cache_dir = os.path.join(cache_base, "cached_images")
        os.makedirs(self.cache_dir, mode=0o755, exist_ok=True)
        self.cache = _open_diskcache(diskcache_dir)

    def request_image(self, image_id):
        print(f"[request_image] Requesting image: {image_id}")

        # Check in memory cache first
        if image_id in self.memory_cache:
            self._update_frequency(image_id)
            print(f"[request_image] Found {image_id} in memory.")
            return self.memory_cache[image_id][0], 'memory'

        # Check in disk cache
        cached_image_data = self.cache.get(image_id)
        if cached_image_data:
            print(f"[request_image] Found {image_id} in disk cache.")
            print(f"[request_image] Cached image data: {cached_image_data}")
            # Load the image from the tar file
            image = self._load_image_from_tar(cached_image_data['tar_path'])
            if image:
                self._store_in_memory(image_id, image)  # Store in memory for faster future access
            return image, 'disk'

        # Pull from Docker Hub and store in memory and disk cache
        print(f"[request_image] Pulling image {image_id}...")
        image = self._pull_from_hub(image_id)

        # Check image size and store in memory and disk cache if within limits
        if image is not None:
            image_size = self._get_image_size(image)  # Use updated method to get size
            print(f"[request_image] Image size: {image_size} bytes")

            # Free up memory space if necessary
            self._evict_memory_cache(image_size)

            if image_size <= self.memory_limit:
                self._store_in_memory(image_id, image)
                self._store_in_disk_cache(image_id, image)
            else:
                print(f"[request_image] Image {image_id} exceeds memory limit of {self.memory_limit} bytes and will not be cached.")

        return image, 'cold'

    def _pull_from_hub(self, image_id):
        print(f"[pull_from_hub] Pulling image {image_id} from Docker Hub...")
        try:
            # Pull the image from Docker Hub
            self.docker_client.images.pull(image_id)
            print(f"[pull_from_hub] Image {image_id} pulled successfully.")
            return self.docker_client.images.get(image_id)
        except Exception as e:
            print(f"[pull_from_hub] Error pulling image {image_id}: {e}")
            return None

    def _load_image_from_tar(self, tar_path):
        """Load the Docker image from a tar file."""
        print(f"[load_image_from_tar] Loading image from tar file: {tar_path}")
        try:
            with open(tar_path, 'rb') as f:
                images = self.docker_client.images.load(f.read())
            if images:
                print(f"[load_image_from_tar] Image loaded from tar file: {tar_path}")
                return images[0]  # Return the first loaded image
            else:
                print(f"[load_image_from_tar] No images were loaded from the tar file: {tar_path}")
                return None
        except Exception as e:
            print(f"[load_image_from_tar] Error loading image from tar file: {tar_path}, Error: {e}")
            return None

    def _get_image_size(self, image):
        """Get the size of the image using the Size attribute."""
        try:
            image_size = image.attrs['Size']
            print(f"[get_image_size] Image size: {image_size} bytes")
            return image_size
        except Exception as e:
            print(f"[get_image_size] Error getting size for image: {e}")
            return 0

    def _store_in_memory(self, image_id, image):
        # Store the Docker image object in memory
        self.memory_cache[image_id] = (image, 1)  # Store the image and initialize frequency
        print(f"[store_in_memory] Stored {image_id} in memory.")

    def _store_in_disk_cache(self, image_id, image):
        # Perform LFU eviction if total disk usage exceeds the limit
        self._evict_disk_cache(image_id, image)

        # Save the image to a tar file
        tar_path = os.path.join(self.cache_dir, f"{image_id.replace(':', '_colon_').replace('/', '_slash_').replace('.', 'dot')}.tar")
        print(f"[store_in_disk_cache] Saving image to tar file: {tar_path}")
        with open(tar_path, 'wb') as f:
            for chunk in image.save():
                f.write(chunk)
        print(f"[store_in_disk_cache] Image saved to tar file: {tar_path}")

        # Store metadata in disk cache
        self.cache[image_id] = {
            'tar_path': tar_path,
            'size': self._get_image_size(image)
        }
        print(f"[store_in_disk_cache] Stored {image_id} in disk cache with tar path: {tar_path}.")

    def _evict_memory_cache(self, new_image_size):
        """Evict LFU items from memory cache until there is enough space."""
        total_size = sum(self._get_image_size(img[0]) for img in self.memory_cache.values())
        print(f"[evict_memory_cache] Total memory cache size: {total_size} bytes")
        
        while (total_size + new_image_size) > self.memory_limit:
            # Find the least frequently used item
            least_frequent_key = min(self.memory_cache.keys(), key=lambda k: self.memory_cache[k][1])
            least_frequent_size = self._get_image_size(self.memory_cache[least_frequent_key][0])
            print(f"[evict_memory_cache] Least frequent image in memory: {least_frequent_key}, Size: {least_frequent_size} bytes")

            # Remove from memory cache
            del self.memory_cache[least_frequent_key]
            print(f"[evict_memory_cache] Evicted {least_frequent_key} from memory cache to maintain memory limit.")
            total_size -= least_frequent_size
            print(f"[evict_memory_cache] Updated total memory cache size: {total_size} bytes")

    def _evict_disk_cache(self, image_id, image):
        """Evict LFU items from disk cache until within limit."""
        image_size = self._get_image_size(image)
        total_size = self.cache.volume()  # Use DiskCache's volume method
        print(f"[evict_disk_cache] Total disk cache size: {total_size} bytes")
        
        while (total_size + image_size) > self.disk_limit:
            # Find the least frequently used item
            least_frequent_key = min(self.cache.keys(), key=lambda k: self.cache[k][1])  # LFU eviction
            least_frequent_size = os.path.getsize(os.path.join(self.cache_dir, least_frequent_key))
            print(f"[evict_disk_cache] Least frequent image in disk cache: {least_frequent_key}, Size: {least_frequent_size} bytes")

            # Remove from disk cache
            del self.cache[least_frequent_key]
            print(f"[evict_disk_cache] Evicted {least_frequent_key} from disk cache to maintain disk limit.")
            total_size -= least_frequent_size
            print(f"[evict_disk_cache] Updated total disk cache size: {total_size} bytes")

    def _update_frequency(self, image_id):
        # Update the frequency of the image in memory cache
        image, frequency = self.memory_cache[image_id]
        self.memory_cache[image_id] = (image, frequency + 1)
        print(f"[update_frequency] Updated frequency for {image_id} in memory cache.")

# Usage Example
if __name__ == "__main__":
    # Create an instance of HybridImageManager with limits
    hybrid_manager = HybridImageManager(memory_limit=100 * 1024 * 1024, disk_limit=1 * 1024 * 1024 * 1024)  # 100 MB memory limit, 1 GB disk limit

    # Request an image
    image = hybrid_manager.request_image("hello-world")

    # Request the same image again
    image_again = hybrid_manager.request_image("hello-world")

    # Use the image
    # ...