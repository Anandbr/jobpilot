import feedparser
import hashlib
import requests
from datetime import datetime
from typing import List, Dict
from config.loader import get_job_search
from tools.database import save_job, get_job


# LinkedIn RSS feed URLs for job searches
# Format: https://www.linkedin.com/jobs/search/?keywords={role}&location={location}&f_TPR=r86400
# f_TPR=r86400 means posted in last 24 hours

def build_linkedin_rss_urls() -> List[str]:
    """
    Build LinkedIn RSS feed URLs from preferences.
    Returns list of URLs to monitor.
    """
    prefs = get_job_search()
    urls = []

    locations = prefs.get("locations", ["Remote"])
    target_roles = prefs.get("target_roles", [])

    # Build URL for each role + location combination
    # Focus on top 3 roles and top 3 locations to avoid too many feeds
    top_roles = target_roles[:3]
    top_locations = locations[:3]

    for role in top_roles:
        for location in top_locations:
            encoded_role = role.replace(' ', '%20')
            encoded_location = location.replace(' ', '%20')
            url = (
                f"https://www.linkedin.com/jobs/search/?keywords={encoded_role}"
                f"&location={encoded_location}"
                f"&f_TPR=r86400"  # Last 24 hours
                f"&position=1&pageNum=0"
            )
            urls.append(url)

    return urls


def fetch_linkedin_jobs() -> List[Dict]:
    """
    Fetch new job listings from LinkedIn.
    Returns list of job dicts.
    """
    prefs = get_job_search()
    jobs = []

    # LinkedIn job search URLs to scrape
    searches = []

    for role in prefs["target_roles"][:4]:
        for location in prefs["locations"][:2]:
            searches.append({
                "role": role,
                "location": location
            })

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }

    for search in searches:
        try:
            role = search["role"].replace(" ", "%20")
            location = search["location"].replace(" ", "%20")

            url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
                f"?keywords={role}&location={location}&start=0"
            )

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                parsed = _parse_linkedin_response(response.text, search["location"])
                jobs.extend(parsed)
                print(f"  [FETCH] {search['role']} in {search['location']}: "
                      f"{len(parsed)} jobs found")
            else:
                print(f"  [FETCH] {search['role']} in {search['location']}: "
                      f"status {response.status_code}")

        except Exception as e:
            print(f"  [FETCH ERROR] {search['role']}: {e}")

    return jobs


def _parse_linkedin_response(html: str, location: str) -> List[Dict]:
    """Parse LinkedIn job listings from HTML response."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    jobs = []

    job_cards = soup.find_all('div', class_='base-card')

    for card in job_cards:
        try:
            # Extract job details
            title_elem = card.find('h3', class_='base-search-card__title')
            company_elem = card.find('h4', class_='base-search-card__subtitle')
            location_elem = card.find('span', class_='job-search-card__location')
            link_elem = card.find('a', class_='base-card__full-link')
            time_elem = card.find('time')

            if not title_elem or not link_elem:
                continue

            title = title_elem.get_text(strip=True)
            company = company_elem.get_text(strip=True) if company_elem else "Unknown"
            job_location = location_elem.get_text(strip=True) if location_elem else location
            url = link_elem.get('href', '').split('?')[0]
            posted_at = time_elem.get('datetime', '') if time_elem else ''

            # Generate stable job ID from URL
            job_id = hashlib.md5(url.encode()).hexdigest()

            jobs.append({
                "id": job_id,
                "title": title,
                "company": company,
                "location": job_location,
                "url": url,
                "posted_at": posted_at,
                "source": "linkedin",
                "jd_text": ""  # Will be fetched separately
            })

        except Exception as e:
            continue

    return jobs


def fetch_job_description(url: str) -> str:
    """
    Fetch the full job description from a job posting URL.
    Returns JD text or empty string if failed.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code != 200:
            return ""

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # LinkedIn job description container
        jd_elem = soup.find('div', class_='description__text')
        if not jd_elem:
            jd_elem = soup.find('div', class_='show-more-less-html__markup')
        if not jd_elem:
            jd_elem = soup.find('section', class_='description')

        if jd_elem:
            return jd_elem.get_text(separator='\n', strip=True)

        return ""

    except Exception as e:
        print(f"  [JD FETCH ERROR] {url}: {e}")
        return ""


def scan_for_new_jobs() -> List[Dict]:
    """
    Main function called by the monitoring loop.
    Fetches jobs, filters duplicates and irrelevant ones,
    returns only new relevant jobs.
    """
    from tools.scorer import quick_keyword_filter
    from tools.ollama_client import quick_relevance_check

    print("\n[SCAN] Checking for new jobs...")

    all_jobs = fetch_linkedin_jobs()
    new_jobs = []
    skipped = 0
    prefs = get_job_search()
    preferred_locations = [l.lower() for l in prefs.get("locations", [])]

    for job in all_jobs:
        # Skip if we already have this job
        existing = get_job(job["id"])
        if existing:
            continue

        # Skip obviously non-US locations
        job_location = job.get("location", "").lower()
        
        #Check if job location matches any preferred location
        location_match = any(
            preferred in job_location
            for preferred in preferred_locations
        )

        if not location_match:
            skipped += 1
            continue

        #Ollama pre-filter - free and fast
        #Catches obvious non-matches before fetching full JD
        title = job.get("title", "")
        company = job.get("company", "")

        try:
            if not quick_relevance_check(title, company):
                print(f" [OLLAMA FILTER] Skipping: {title} at {company}")
                skipped += 1
                continue
        except Exception as e:
            #If Ollama is down - skip filter, continue normally
            print(f" [OLLAMA WARNING] {e} - skipping pre-filter")

        # Fetch full JD first
        if job["url"]:
            print(f"  [JD] Fetching: {job['title']} at {job['company']}...")
            job["jd_text"] = fetch_job_description(job["url"])

        # Run keyword filter — only save relevant jobs
        if job["jd_text"] and not quick_keyword_filter(job["jd_text"]):
            skipped += 1
            continue

        # Save to database
        save_job(job)
        new_jobs.append(job)

    print(f"[SCAN] {len(new_jobs)} relevant new jobs | "
          f"{skipped} skipped | {len(all_jobs)} total found")
    return new_jobs