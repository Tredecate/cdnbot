import boto3
import requests

from config import settings
from log import debug_log


class BucketClient():
    def __init__(self):
        self.client = boto3.client(
            service_name="s3",
            region_name=settings.bucket_region,
            endpoint_url=settings.bucket_url,
            aws_access_key_id=settings.bucket_access_key_id,
            aws_secret_access_key=settings.bucket_secret_access_key.get_secret_value(),
        )

        self.cdn_cache_token = settings.cdn_cache_token.get_secret_value()
        self.cdn_cache_purge_url = settings.cdn_cache_purge_url

        self.bucket_name = settings.bucket_name

    def upload_file(self, object_name, file_data):
        self.client.put_object(Bucket=self.bucket_name, Key=object_name, Body=file_data)

    def delete_file(self, object_name):
        self.client.delete_object(Bucket=self.bucket_name, Key=object_name)

    def get_file(self, object_name):
        response = self.client.get_object(Bucket=self.bucket_name, Key=object_name)
        return response["Body"].read()

    def get_file_tree(self, prefix):
        paginator = self.client.get_paginator("list_objects_v2")
        page_iterator = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)

        file_tree = []
        for page in page_iterator:
            if "Contents" in page:
                for obj in page["Contents"]:
                    file_tree.append(obj["Key"])

        return file_tree

    def purge_cache(self, prefix):
        if not self.cdn_cache_purge_url:
            raise ValueError("CDN cache purge URL is not configured.")

        headers = {
            "Authorization": f"Bearer {self.cdn_cache_token}",
            "Content-Type": "application/json",
        }

        data = {
            "prefixes": [prefix]
        }

        response = requests.post(self.cdn_cache_purge_url, headers=headers, json=data)

        if response.status_code != 200:
            debug_log(f"Failed to purge CDN cache for prefix {prefix}. Status code: {response.status_code}, Response: {response.text}", level=1)
            raise ValueError("Failed to purge CDN cache.")
        
        return response.json()
    
client = BucketClient()