#! /usr/bin/env python3

import asyncio
import json
import os
from pathlib import Path

import requests
import urllib3
from pyppeteer import launch
from rich.progress import Progress

urllib3.disable_warnings()


async def create_directory(base_path, *path_components):
    """
    Creates a directory path if it doesn't exist.

    Args:
        base_path (str): Base directory path
        *path_components: Additional path components to append

    Returns:
        Path: The created directory path object
    """
    directory_path = Path(base_path)
    for component in path_components:
        directory_path = directory_path / component
    directory_path.mkdir(parents=True, exist_ok=True)
    return directory_path


async def download_benchmark_file(
    document_id, download_url, file_path, progress_indicator
):
    """
    Downloads a file from the specified URL with progress tracking.

    Args:
        document_id (str): Document ID for cookie authentication
        download_url (str): URL to download the file from
        file_path (str): Local path to save the downloaded file
        progress_indicator (str): Progress indicator string (e.g., "1/10")

    Returns:
        None: Returns None if file already exists or after successful download
    """
    file_name = os.path.basename(file_path)
    if os.path.exists(file_path):
        print(
            f"\r{progress_indicator} File already exists: {file_name}",
            end="",
            flush=True,
        )
        return None
    cookies = {
        "documentId": str(document_id),
    }
    response = requests.get(download_url, cookies=cookies, verify=False, stream=True)
    response.raise_for_status()
    total_size = int(response.headers.get("content-length", 0))
    with open(file_path, "wb") as f:
        with Progress() as progress:
            task = progress.add_task(f"{file_name} Downloading...", total=total_size)
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    progress.update(task, advance=len(chunk))
    return None


async def extract_document_info(json_data):
    """
    Extracts document information from JSON data.

    Args:
        json_data (dict): JSON data containing document information

    Returns:
        dict: Dictionary with document IDs as keys and document information as values
    """
    document_info = {}
    json_dumps = json.dumps(json_data)
    dict_data = json.loads(json_dumps)
    for category in dict_data:
        for document in category["documents"]:
            document_info[document["id"]] = {}
            document_info[document["id"]]["pardot-id"] = document["pardot-id"]
            document_info[document["id"]]["filename"] = document["filename"]
    return document_info


async def fetch_technology_categories():
    """
    Fetches all available technology categories from CIS website.

    Returns:
        dict: Dictionary mapping technology IDs to their folder paths
    """
    technology_paths = {}
    headers = {
        "Host": "downloads.cisecurity.org",
        "Sec-Ch-Ua-Platform": '"macOS"',
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "en-US,en;q=0.9",
        "Sec-Ch-Ua-Mobile": "?0",
        "Accept": "*/*",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
        "Referer": "https://downloads.cisecurity.org/",
        # 'Accept-Encoding': 'gzip, deflate, br',
        "Priority": "u=1, i",
    }

    response = requests.get(
        "https://downloads.cisecurity.org/technology", headers=headers, verify=False
    )
    response_json = response.json()
    categories_dict = json.loads(json.dumps(response_json))

    for category_key in categories_dict.keys():
        for item in categories_dict[category_key]:
            full_folder_path = os.path.join(category_key, item["title"])
            technology_paths[str(item["id"])] = full_folder_path
            await create_directory(full_folder_path)
    return technology_paths


async def process_benchmark_response(response, technologies_dict):
    """
    Processes browser responses to extract benchmark information.

    Args:
        response: Pyppeteer response object
        technologies_dict (dict): Dictionary containing technology information

    Returns:
        dict: Updated technologies_dict with resource information
    """
    for tech_id in technologies_dict.keys():
        if response.url.endswith(str(tech_id) + "/benchmarks/latest"):
            json_data = await response.json()
            document_info = await extract_document_info(json_data)
            for resource_id in document_info.keys():
                benchmark_resource = {}
                pdf_url = (
                    "https://learn.cisecurity.org"
                    + document_info[resource_id]["pardot-id"]
                )
                filename = os.path.join(
                    technologies_dict[tech_id]["tech_path"],
                    document_info[resource_id]["filename"],
                )
                benchmark_resource["resource_id"] = resource_id
                benchmark_resource["resource_filename"] = filename
                benchmark_resource["resource_pdf_url"] = pdf_url
                technologies_dict[tech_id]["resource_list"].append(benchmark_resource)
    return technologies_dict


async def main():
    """
    Main function that orchestrates the entire process:
    1. Fetches technology categories
    2. Creates a headless browser to navigate CIS website
    3. Intercepts responses to extract benchmark information
    4. Downloads all benchmark PDFs with progress tracking
    """
    technologies_dict = {}
    # CIS benchmarks download URL
    cis_portal_url = "https://downloads.cisecurity.org/#/"
    technology_paths = await fetch_technology_categories()
    for tech_id, tech_path in technology_paths.items():
        technologies_dict[tech_id] = {}
        technologies_dict[tech_id]["tech_path"] = tech_path
        technologies_dict[tech_id]["resource_list"] = []
    browser = await launch()
    page = await browser.newPage()
    await page.goto(cis_portal_url)

    # Capture responses
    page.on(
        "response",
        lambda response: asyncio.ensure_future(
            process_benchmark_response(response, technologies_dict)
        ),
    )

    # Keep the browser open for a bit to collect responses
    await asyncio.sleep(5)

    total_benchmarks = 0
    for tech_id in technologies_dict.keys():
        resources_list = technologies_dict[tech_id]["resource_list"]
        total_benchmarks += len(resources_list)

    current_benchmark = 1
    for tech_id in technologies_dict.keys():
        resources_list = technologies_dict[tech_id]["resource_list"]
        for benchmark in resources_list:
            document_id = benchmark["resource_id"]
            file_path = benchmark["resource_filename"]
            download_url = benchmark["resource_pdf_url"]
            progress_indicator = f"{current_benchmark}/{total_benchmarks}"
            await download_benchmark_file(
                document_id, download_url, file_path, progress_indicator
            )
            current_benchmark += 1

    await browser.close()


asyncio.run(main())
