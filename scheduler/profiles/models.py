from django.db import models
from pytz import timezone
from django.db.models import F
import pytz
from django.apps import apps
from datetime import datetime, timedelta
import uuid
from scheduler.settings import TIME_ZONE
# from developers.models import Services
from django.core.serializers.json import DjangoJSONEncoder
import json
# from developers.models import Services


class User(models.Model):
    user_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_provider = models.BooleanField(default=False)
    is_developer = models.BooleanField(default=False)
    active = models.BooleanField(default=False)
    ready = models.BooleanField(default=False)
    last_ready_signal = models.DateTimeField(default=datetime.now)
    location = models.CharField(max_length=30, blank=True)
    ram = models.IntegerField(default=0)
    cpu = models.IntegerField(default=0)
    cpu_efficiency_score = models.DecimalField(null=True, max_digits=30, decimal_places=15)
    memory_efficiency_score = models.DecimalField(null=True, max_digits=30, decimal_places=15)
    # Machine benchmark fields used by the CPI-based runtime prediction strategy.
    # Populated by a one-time machine benchmarking script; nullable so the system
    # keeps running before benchmarks have been collected.
    cpi = models.DecimalField(null=True, blank=True, max_digits=10, decimal_places=4)
    memory_bandwidth = models.DecimalField(null=True, blank=True, max_digits=20, decimal_places=4)
    clock_hz = models.BigIntegerField(null=True, blank=True)
    # network_bandwidth = models.DecimalField(null=True, max_digits=30, decimal_places=15)
    # gpu_available = models.BooleanField(default=False)

    # NOTE Provider - Only fields
    function_invocations = models.JSONField(default=dict, blank=True, null=True)  # { function_id [str] : invocation_count [int] }
    cached_images = models.JSONField(default=dict, blank=True, null=True)  # { service_id: {"location": "memory|disk", "frequency": int, "last_used": timestamp, "size": int} }
    disk_cache_usage = models.IntegerField(default=0)  # Total disk cache usage in bytes
    reputation_score = models.IntegerField(default=0, null=True) # int
    delay = models.JSONField(default=dict, null=True)
    """{ 
            "time_of_last_startjob" : timestamp [datetime], 
            "inflight_jobs": { 
                "job_id" : estimated_runtime [int]
            }
        }
    """
    # time_of_last_startjob = models.DateTimeField(null=True, blank=True)
    # inflight_jobs = models.JSONField(default=dict, blank=True, null=True)

    """
    resolves a case that may occur even with other checks: -> non - provider has provider only fields populated
    """

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(is_provider=True)
                | models.Q(function_invocations__len=0),
                name="function_invocation_only_if_provider",
            ),
            models.CheckConstraint(
                condition=models.Q(is_provider=True) | models.Q(delay={}),
                name="delay_only_if_provider",
            ),
            models.CheckConstraint(
                condition=models.Q(is_provider=True) | models.Q(cached_images={}),
                name="cached_images_only_if_provider",
            ),
        ]

    #NOTE This needs to have knowledge of the user's cache limit, based on which it will remove least frequently used.
    def _ensure_delay_shape(self):
        """Normalize legacy/invalid delay payloads to the expected dict shape."""
        if not isinstance(self.delay, dict):
            self.delay = {}
        inflight = self.delay.get("inflight_jobs")
        if not isinstance(inflight, list):
            self.delay["inflight_jobs"] = []
        last = self.delay.get("time_of_last_startjob")
        # Keep a datetime if already parsed, else reset to 0 sentinel.
        if not isinstance(last, datetime):
            self.delay["time_of_last_startjob"] = 0

    def add_inflight_job(self, job_id, estimated_runtime):
        # Add a service ID to the inflight jobs at the end
        if job_id not in self.inflight_jobs:
            self.inflight_jobs.append(job_id)
            self.save()

    # if no args are passed, it will remove the first element from the inflight jobs array
    def remove_inflight_job(self, job_id=None):
        # Remove a service ID from the inflight jobs.
        if job_id is not None:
            if self.inflight_jobs:
                if job_id in self.inflight_jobs:
                    self.inflight_jobs.remove(job_id)
                    self.save()
        else:
            if self.inflight_jobs:
                self.inflight_jobs.pop(0)
                self.save()

    def increment_reputation(self, amount=1):
        self.reputation_score += amount

    def decrement_reputation(self, amount=1):
        self.reputation_score -= amount

    def reset_delay(self):
        self._ensure_delay_shape()
        self.delay["time_of_last_startjob"] = 0
        self.delay["inflight_jobs"] = []
        self.save()

    def add_delay(self, new_delay):
        print(f"\nEntering add_delay")
        print(f"Current delay state: {self.delay}")
        print(f"New delay value: {new_delay}")
        print(f"Type of new delay: {type(new_delay)}")
        
        try:
            self._ensure_delay_shape()
            if isinstance(new_delay, dict):
                print("Converting dict to JSON string")
                new_delay = json.dumps(new_delay, cls=DjangoJSONEncoder)
            
            print(f"Appending to inflight_jobs: {new_delay}")
            self.delay["inflight_jobs"].append(new_delay)
            
            if len(self.delay["inflight_jobs"]) == 1:
                current_time = datetime.now()
                print(f"Setting time_of_last_startjob to: {current_time}")
                # Convert datetime to ISO format string before saving
                self.delay["time_of_last_startjob"] = current_time.isoformat()

            #NOTE this can be used to parse it back to datetime object
            # datetime.fromisoformat(self.delay["time_of_last_startjob"])
            
            print(f"Final delay state: {self.delay}")
            self.save()
            print("Successfully saved in add_delay")
        except Exception as e:
            print(f"Error in add_delay: {str(e)}")
            print(f"Current object state: {self.__dict__}")
            raise

        print("Exiting add_delay\n")

    #NOTE It is assummed that this is the case pertaining to "just before job completion".
    def calculate_current_delay(self, time_of_last_startjob):
        """
        This calculation is only done when needed (i.e. just before job creation)
        """
        self._ensure_delay_shape()
        if not self.delay["inflight_jobs"]:
            print(f"No inflight jobs for {self.user_id}")
            return 0

        # elapsed time since the last job started
        current_time = datetime.now()
        if not isinstance(self.delay["time_of_last_startjob"], datetime):
            return 0
        elapsed_time = (current_time - self.delay["time_of_last_startjob"]).total_seconds()

        remaining_time_for_current_job = max(0, self.delay["time_of_last_startjob"] - elapsed_time)

        total_delay =  + sum(self.delay["inflight_jobs"][:]) - remaining_time_for_current_job

        return total_delay

    def update_delay_after_completion(self, time_of_last_startjob):
        """
        Updates delay after a job completion.
         -> Remove the oldest predicted runtime
         -> adjust time_of_last_startjob
        """
        self._ensure_delay_shape()
        if not self.delay["inflight_jobs"]:
            return

        # current_time = datetime.now().timestamp()
        # elapsed_time = current_time - self.delay["time_of_last_startjob"]

        # Remove the predicted runtime of the completed job (the oldest one)
        self.delay["inflight_jobs"].pop(0)
        self.delay["time_of_last_startjob"] = time_of_last_startjob
        self.save()

    def update_delay_after_start(self, time_of_last_startjob):
        self._ensure_delay_shape()
        self.delay["time_of_last_startjob"] = time_of_last_startjob

    def satisfies(self, requirements):
        # requirements expected to be a dict with key - value pairs like ram, cpu, gpu, etc.

        # specs dict should be changed as and how the extent of requirements are
        specifications = {
            "memory_limit": self.ram,
            "cpu_cores": self.cpu,
            # "network_bandwidth": getattr(self, "network_bandwidth", 0),
            # "ram": self.ram,
            # "cpu": self.cpu,
            # 'gpu_required' : self.gpu_available,
        }

        # return True if specs are better than
        for key, value in requirements.items():
            if key not in specifications:
                return False
            if isinstance(value, bool):  # suppose a spec is "gpu_available" : True
                if specifications[key] != value:
                    return False
            if specifications[key] < value:
                return False
        return True

    def get_compatible_services(self):
        """
        Retrieves services that the provider can handle based on their specifications.
        Returns a QuerySet compatible Services.
        """
        Services = apps.get_model("developers", "Services")
        # Services referenced this way to resolve circular import.
        # syntax = ModelClass = apps.get_model('app_label', 'ModelName')
        return Services.objects.filter(
            provider=self,
            active=True,
            requirements__ram__lte=self.ram,
            requirements__cpu__lte=self.cpu,
            # requirements__gpu_required=self.gpu_available,
            # Add other requirements as needed
        )

    # return a dict mapping each compatible service to its predicted runtime
    def get_predicted_runtimes(self):
        pred_rt_matrix = {
            service.name: service.predict_runtime()
            for service in self.get_compatible_services()
        }
        return pred_rt_matrix

    def __str__(self):
        return f"User : {self.user_id}\n  \tprovider : {self.is_provider} \tdeveloper : {self.is_developer}"

    def get_last_start_time(self):
        # Assuming Job has a foreign key to User as provider
        Job = apps.get_model('providers', 'Job')
        last_job = Job.objects.filter(provider=self).order_by('-start_time').first()
        return last_job.start_time if last_job else None

    def is_service_cached(self, service_id):
        """
        Check if a service is cached on this provider.
        
        Args:
            service_id: The ID of the service to check
            
        Returns:
            bool: True if the service is cached, False otherwise
        """
        return str(service_id) in self.cached_images
        
    def get_cache_location(self, service_id):
        """
        Get the cache location for a service (memory or disk).
        
        Args:
            service_id: The ID of the service to check
            
        Returns:
            str: 'memory', 'disk', or None if not cached
        """
        service_id = str(service_id)
        if service_id in self.cached_images:
            return self.cached_images[service_id]['location']
        return None
        
    def _get_total_memory_usage(self):
        """
        Calculate total memory usage of cached images.
        
        Returns:
            int: Total memory usage in bytes
        """
        return sum(
            entry['size'] 
            for entry in self.cached_images.values() 
            if entry['location'] == 'memory'
        )
        
    def _evict_memory_cache(self, new_image_size, memory_limit):
        """
        Evict LFU items from memory cache until there is enough space.
        
        Args:
            new_image_size: Size of the new image to be cached
            memory_limit: Maximum memory limit in bytes
            
        Returns:
            bool: True if eviction made enough space, False if impossible
        """
        total_size = self._get_total_memory_usage()
        print(f"[evict_memory_cache] Total memory cache size: {total_size} bytes")
        
        disk_limit = self.ram * 1024 * 1024 * 2  # Disk limit is 2x RAM
        
        # If the new image is larger than the total memory limit, we can't cache it
        if new_image_size > memory_limit:
            print(f"[evict_memory_cache] New image size ({new_image_size}) exceeds total memory limit ({memory_limit})")
            return False
        
        # Eviction attempts counter to prevent infinite loops
        eviction_attempts = 0
        max_eviction_attempts = 20  # Higher than disk since we're trying both memory and disk eviction
        
        while (total_size + new_image_size) > memory_limit and eviction_attempts < max_eviction_attempts:
            eviction_attempts += 1
            
            # Find the least frequently used item in memory
            memory_cached = {
                service_id: entry 
                for service_id, entry in self.cached_images.items() 
                if entry['location'] == 'memory'
            }
            
            if not memory_cached:
                print("[evict_memory_cache] No items in memory cache to evict")
                return total_size + new_image_size <= memory_limit
            
            # Find the least frequently used item
            least_frequent_key = min(
                memory_cached.keys(), 
                key=lambda k: memory_cached[k]['frequency']
            )
            least_frequent_size = memory_cached[least_frequent_key]['size']
            
            print(f"[evict_memory_cache] Least frequent image in memory: {least_frequent_key}, Size: {least_frequent_size} bytes")
            
            # Check if there's room on disk, if not evict from disk first
            if (self.disk_cache_usage + least_frequent_size) > disk_limit:
                print(f"[evict_memory_cache] Disk cache would exceed limit, need to evict from disk first")
                # Evict from disk to make room
                disk_eviction_success = self._evict_disk_cache(least_frequent_size, disk_limit)
                
                # If disk is still full after eviction attempts, just remove from memory without moving to disk
                if not disk_eviction_success:
                    print(f"[evict_memory_cache] Disk cache still full after eviction, removing {least_frequent_key} completely")
                    del self.cached_images[least_frequent_key]
                    total_size -= least_frequent_size
                    print(f"[evict_memory_cache] Updated total memory cache size: {total_size} bytes")
                    continue
            
            # Move to disk cache
            self.cached_images[least_frequent_key]['location'] = 'disk'
            self.disk_cache_usage += least_frequent_size
            print(f"[evict_memory_cache] Moved {least_frequent_key} to disk cache. Disk usage now: {self.disk_cache_usage} bytes")
            
            total_size -= least_frequent_size
            print(f"[evict_memory_cache] Updated total memory cache size: {total_size} bytes")
        
        self.save()
        
        # Check if we made enough space
        success = total_size + new_image_size <= memory_limit
        print(f"[evict_memory_cache] {'Successfully' if success else 'Failed to'} free enough memory space")
        
        return success
        
    def _evict_disk_cache(self, new_image_size, disk_limit):
        """
        Evict LFU items from disk cache until within limit.
        
        Args:
            new_image_size: Size of the new image to be cached
            disk_limit: Maximum disk cache limit in bytes
            
        Returns:
            bool: True if eviction made enough space, False if impossible
        """
        print(f"[evict_disk_cache] Total disk cache size: {self.disk_cache_usage} bytes")
        print(f"[evict_disk_cache] Need to free {new_image_size} bytes, limit is {disk_limit} bytes")
        
        # Check if the new image exceeds disk limit entirely
        if new_image_size > disk_limit:
            print(f"[evict_disk_cache] New image size ({new_image_size}) exceeds total disk limit ({disk_limit})")
            return False
        
        # Try to evict until we have enough space
        eviction_attempts = 0
        max_eviction_attempts = 10  # Prevent infinite loops
        
        while (self.disk_cache_usage + new_image_size) > disk_limit and eviction_attempts < max_eviction_attempts:
            eviction_attempts += 1
            
            # Find the least frequently used item in disk cache
            disk_cached = {
                service_id: entry 
                for service_id, entry in self.cached_images.items() 
                if entry['location'] == 'disk'
            }
            
            if not disk_cached:
                print("[evict_disk_cache] No items in disk cache to evict")
                return self.disk_cache_usage + new_image_size <= disk_limit
            
            # Find the least frequently used item
            least_frequent_key = min(
                disk_cached.keys(), 
                key=lambda k: disk_cached[k]['frequency']
            )
            least_frequent_size = disk_cached[least_frequent_key]['size']
            
            print(f"[evict_disk_cache] Least frequent image in disk cache: {least_frequent_key}, Size: {least_frequent_size} bytes")
            
            # Remove from disk cache
            del self.cached_images[least_frequent_key]
            self.disk_cache_usage -= least_frequent_size
            print(f"[evict_disk_cache] Evicted {least_frequent_key} from disk cache to maintain disk limit.")
            print(f"[evict_disk_cache] Updated total disk cache size: {self.disk_cache_usage} bytes")
        
        self.save()
        
        # Check if we managed to free enough space
        success = self.disk_cache_usage + new_image_size <= disk_limit
        print(f"[evict_disk_cache] {'Successfully' if success else 'Failed to'} free enough space")
        
        return success
        
    def update_frequency(self, service_id):
        """
        Update the frequency of a cached service.
        
        Args:
            service_id: The ID of the service
        """
        service_id = str(service_id)
        if service_id in self.cached_images:
            self.cached_images[service_id]['frequency'] += 1
            self.cached_images[service_id]['last_used'] = datetime.now().isoformat()
            self.save()
            print(f"[update_frequency] Updated frequency for {service_id} in cache.")
        
    def update_cache_state(self, service_id, location, image_size, increment_frequency=True):
        """
        Update the cache state for a service.
        
        Args:
            service_id: The ID of the service
            location: 'memory' or 'disk'
            image_size: Size of the image in bytes
            increment_frequency: Whether to increment the usage frequency
            
        Returns:
            bool: True if update was successful, False if cache could not accommodate the image
        """
        service_id = str(service_id)
        current_time = datetime.now().isoformat()
        
        # Check if this service is already cached
        existing_cache = service_id in self.cached_images
        
        if location == 'memory':
            # Check memory capacity
            memory_limit = self.ram * 1024 * 1024  # Convert RAM from MB to bytes
            
            # If image is larger than total memory, we can't cache it
            if image_size > memory_limit:
                print(f"[update_cache_state] Image size ({image_size}) exceeds total memory limit ({memory_limit})")
                return False
                
            # Try to evict items from memory cache
            total_memory_used = self._get_total_memory_usage()
            if total_memory_used + image_size > memory_limit:
                self._evict_memory_cache(image_size, memory_limit)
                
                # Check if eviction made enough space
                if self._get_total_memory_usage() + image_size > memory_limit:
                    print(f"[update_cache_state] Failed to make enough space in memory cache")
                    return False
        
        elif location == 'disk':
            # Check disk capacity
            disk_limit = self.ram * 1024 * 1024 * 2  # Disk limit is 2x RAM
            
            # If not already cached on disk, make space
            if not existing_cache or self.cached_images[service_id]['location'] != 'disk':
                # Try to evict from disk if needed
                if self.disk_cache_usage + image_size > disk_limit:
                    eviction_success = self._evict_disk_cache(image_size, disk_limit)
                    if not eviction_success:
                        print(f"[update_cache_state] Could not make enough space in disk cache")
                        return False
        
        # Update or create the cache entry
        if existing_cache:
            # Update existing entry
            cache_entry = self.cached_images[service_id]
            old_location = cache_entry['location']
            old_size = cache_entry['size']
            
            # Update disk usage if location changed
            if old_location == 'disk' and location != 'disk':
                self.disk_cache_usage -= old_size
            elif old_location != 'disk' and location == 'disk':
                self.disk_cache_usage += image_size
                
            cache_entry['location'] = location
            cache_entry['last_used'] = current_time
            cache_entry['size'] = image_size
            if increment_frequency:
                cache_entry['frequency'] = cache_entry.get('frequency', 0) + 1
        else:
            # Create new entry
            self.cached_images[service_id] = {
                'location': location,
                'frequency': 1 if increment_frequency else 0,
                'last_used': current_time,
                'size': image_size
            }
                
            if location == 'disk':
                self.disk_cache_usage += image_size
        
        self.save()
        return True

    def remove_from_cache(self, service_id):
        """
        Remove a service from the cache state.
        
        Args:
            service_id: The ID of the service to remove
        """
        service_id = str(service_id)
        if service_id in self.cached_images:
            entry = self.cached_images[service_id]
            if entry['location'] == 'disk':
                self.disk_cache_usage -= entry['size']
            del self.cached_images[service_id]
            self.save()
            
    def get_cached_services(self):
        """
        Get all cached services.
        
        Returns:
            dict: Dictionary of all cached services with their state
        """
        return self.cached_images


# class ServiceInvocationLog(models.Model):
#     provider = models.ForeignKey(
#         User,
#         on_delete=models.CASCADE,
#         limit_choices_to={"is_provider": True},
#         null=False,
#         blank=False,
#         related_name="service_invocation_logs_as_provider",
#         # it's not possible for a Job instance to not have a provider.
#     ), 
#     service = models.ForeignKey(
#         Services,
#         on_delete=models.CASCADE,
#         null=True,
#         blank=True,
#     ),
#     frequency = models.IntegerField(default=0)

#     def __str__(self) -> str:
#         return f"InvtaionLog for provider {self.provider.user_id} and service {self.service.id}"

#     # Constraint => only one entry for a unique pair of provider - service

#     #NOTE for when the service encounters the provider for the first time.
#     def handle_service_invocation(self, service_id,provider_id):
#         # if entry with service_id and provider_id does not exist, create a new entry.else increment the frequency.
#         if not ServiceInvocationLog.objects.filter(service=service_id, provider=provider_id).exists():
#             ServiceInvocationLog.objects.create(service=service_id, provider=provider_id, frequency=1)
#         else:
#             ServiceInvocationLog.objects.filter(service=service_id, provider=provider_id).update(frequency=F('frequency')+1)
