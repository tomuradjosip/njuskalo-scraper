#!/usr/bin/env python3
"""
Njuskalo Scraping Pipeline
=========================

This pipeline runs the complete Njuskalo scraping process in the correct order:

1. njuskalo_category_tree_scraper.py - Scrape category tree and URLs
2. scrape_leaf_entries.py - Scrape individual ad HTML pages
3. fetch_phones_from_api.py - Fetch phone numbers via API
4. parser_ultrafast.py - Parse HTML to structured JSON

Usage:
    python pipeline.py [--step STEP] [--skip-existing] [--url URL] [--run NAME] [--polite]

Options:
    --step STEP              Run specific step only (1-4)
    --skip-existing          Skip pipeline steps if their output already exists
    --url URL                Scrape a single filtered Njuskalo search URL (skips step 1)
    --run NAME               Isolate outputs under backend/runs/<NAME>/
    --polite                 Safer pacing for large scrapes (1 concurrent, ~2s delay)
    --local-only             Never use proxies during scrape
    --skip-existing-html     Skip ads that already have HTML (resume without refetch)
    --concurrency N          Max parallel ad downloads
    --delay SECONDS          Delay between ad request starts
    --page-delay SECONDS     Delay between search result pages
"""

import os
import sys
import time
import subprocess
import argparse
from datetime import datetime
import logging

from run_paths import resolve_paths

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [PIPELINE] %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('pipeline.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

class PipelineRunner:
    def __init__(
        self,
        skip_existing=False,
        custom_url=None,
        run_name=None,
        polite=False,
        concurrency=None,
        delay=None,
        page_delay=None,
        local_only=False,
        skip_existing_html=False,
    ):
        self.skip_existing = skip_existing
        self.custom_url = custom_url
        self.run_name = run_name
        self.polite = polite
        self.concurrency = concurrency
        self.delay = delay
        self.page_delay = page_delay
        self.local_only = local_only
        self.skip_existing_html = skip_existing_html
        self.paths = resolve_paths(run_name)
        self.start_time = time.time()
        self.step_times = {}

    def run_extra_args(self, *args):
        extra = list(args)
        if self.run_name:
            extra.extend(['--run', self.run_name])
        if self.polite:
            extra.append('--polite')
        if self.concurrency is not None:
            extra.extend(['--concurrency', str(self.concurrency)])
        if self.delay is not None:
            extra.extend(['--delay', str(self.delay)])
        if self.page_delay is not None:
            extra.extend(['--page-delay', str(self.page_delay)])
        if self.local_only:
            extra.append('--local-only')
        if self.skip_existing_html:
            extra.append('--skip-existing')
        return extra or None
        
    def run_script(self, script_name, step_num, description, extra_args=None):
        """Run a Python script and track execution time"""
        cmd = [sys.executable, script_name] + (extra_args or [])
        logging.info(f"=" * 60)
        logging.info(f"STEP {step_num}: {description}")
        logging.info(f"Running: {' '.join(cmd)}")
        logging.info(f"=" * 60)
        
        step_start = time.time()
        
        try:
            # Run the script
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding='utf-8'
            )
            
            step_duration = time.time() - step_start
            self.step_times[f"Step {step_num}"] = step_duration
            
            if result.returncode == 0:
                logging.info(f"✅ STEP {step_num} COMPLETED in {step_duration:.2f}s")
                logging.info(f"Output:\n{result.stdout}")
                return True
            else:
                logging.error(f"❌ STEP {step_num} FAILED in {step_duration:.2f}s")
                logging.error(f"Error output:\n{result.stderr}")
                logging.error(f"Standard output:\n{result.stdout}")
                return False
                
        except Exception as e:
            step_duration = time.time() - step_start
            self.step_times[f"Step {step_num}"] = step_duration
            logging.error(f"❌ STEP {step_num} CRASHED in {step_duration:.2f}s: {e}")
            return False
    
    def check_output_exists(self, paths):
        """Check if output files/directories exist"""
        for path in paths:
            if os.path.exists(path):
                if os.path.isdir(path):
                    files = os.listdir(path)
                    if len(files) > 0:
                        return True
                else:
                    return True
        return False
    
    def step1_category_scraper(self):
        """Step 1: Scrape category tree and URLs"""
        if self.custom_url:
            logging.info("⏭️  STEP 1 SKIPPED: Using custom filtered URL")
            return True

        if self.skip_existing:
            # Check if category URLs already exist
            if self.check_output_exists(['category_urls.json', 'categories.json']):
                logging.info("⏭️  STEP 1 SKIPPED: Category data already exists")
                return True
        
        return self.run_script(
            'njuskalo_category_tree_scraper.py',
            1,
            'Scraping category tree and collecting URLs'
        )
    
    def step2_scrape_entries(self):
        """Step 2: Scrape individual ad HTML pages"""
        if self.skip_existing:
            if self.check_output_exists([self.paths['website']]):
                logging.info("⏭️  STEP 2 SKIPPED: HTML files already exist")
                return True
        
        extra = []
        if self.custom_url:
            extra.extend(['--url', self.custom_url])
        return self.run_script(
            'scrape_leaf_entries.py',
            2,
            'Scraping individual ad HTML pages',
            extra_args=self.run_extra_args(*extra),
        )
    
    def step3_fetch_phones(self):
        """Step 3: Fetch phone numbers via API"""
        if self.skip_existing:
            if self.check_output_exists([self.paths['phone_db']]):
                logging.info("⏭️  STEP 3 SKIPPED: Phone database already exists")
                return True
        
        # Phone fetcher only needs --run (rate flags are scrape-only)
        extra = ['--run', self.run_name] if self.run_name else None
        return self.run_script(
            'fetch_phones_from_api.py',
            3,
            'Fetching phone numbers via API',
            extra_args=extra,
        )
    
    def step4_parse_ultrafast(self):
        """Step 4: Parse HTML to structured JSON"""
        if self.skip_existing:
            if self.check_output_exists([self.paths['json']]):
                logging.info("⏭️  STEP 4 SKIPPED: JSON files already exist")
                return True
        
        extra = ['--run', self.run_name] if self.run_name else None
        return self.run_script(
            'parser_ultrafast.py',
            4,
            'Parsing HTML to structured JSON (ultrafast)',
            extra_args=extra,
        )
    
    def run_full_pipeline(self):
        """Run the complete pipeline"""
        logging.info("🚀 STARTING NJUSKALO SCRAPING PIPELINE")
        logging.info(f"Started at: {datetime.now().isoformat()}")
        if self.run_name:
            logging.info(f"Run folder: {self.paths['root']}")
        
        steps = [
            (self.step1_category_scraper, "Category Tree Scraper"),
            (self.step2_scrape_entries, "HTML Page Scraper"),
            (self.step3_fetch_phones, "Phone Number Fetcher"),
            (self.step4_parse_ultrafast, "Ultrafast Parser")
        ]
        
        failed_steps = []
        
        for i, (step_func, step_name) in enumerate(steps, 1):
            success = step_func()
            if not success:
                failed_steps.append(f"Step {i}: {step_name}")
                logging.error(f"Pipeline stopped at Step {i} due to failure")
                break
        
        # Final summary
        total_time = time.time() - self.start_time
        logging.info("=" * 60)
        logging.info("🏁 PIPELINE SUMMARY")
        logging.info("=" * 60)
        
        if failed_steps:
            logging.error(f"❌ Pipeline FAILED at: {', '.join(failed_steps)}")
        else:
            logging.info("✅ Pipeline COMPLETED SUCCESSFULLY!")
        
        logging.info(f"Total execution time: {total_time:.2f}s")
        
        # Step-by-step timing - fixed logic
        for step, duration in self.step_times.items():
            # Extract step number from step name (e.g., "Step 1" -> 1)
            step_num = int(step.split()[1])
            
            # Check if this step failed by looking if there are any failed steps 
            # and if this step number is at or after the first failed step
            if failed_steps:
                first_failed_step = int(failed_steps[0].split()[1])
                status = "❌" if step_num >= first_failed_step else "✅"
            else:
                status = "✅"
                
            logging.info(f"{status} {step}: {duration:.2f}s")
        
        return len(failed_steps) == 0
    
    def run_single_step(self, step_num):
        """Run a single step of the pipeline"""
        steps = {
            1: (self.step1_category_scraper, "Category Tree Scraper"),
            2: (self.step2_scrape_entries, "HTML Page Scraper"), 
            3: (self.step3_fetch_phones, "Phone Number Fetcher"),
            4: (self.step4_parse_ultrafast, "Ultrafast Parser")
        }
        
        if step_num not in steps:
            logging.error(f"Invalid step number: {step_num}. Must be 1-4.")
            return False
        
        step_func, step_name = steps[step_num]
        logging.info(f"🎯 RUNNING SINGLE STEP {step_num}: {step_name}")
        if self.run_name:
            logging.info(f"Run folder: {self.paths['root']}")
        
        success = step_func()
        total_time = time.time() - self.start_time
        
        if success:
            logging.info(f"✅ Step {step_num} completed successfully in {total_time:.2f}s")
        else:
            logging.error(f"❌ Step {step_num} failed after {total_time:.2f}s")
        
        return success

def main():
    parser = argparse.ArgumentParser(
        description='Njuskalo Scraping Pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        '--step', 
        type=int, 
        choices=[1, 2, 3, 4],
        help='Run specific step only (1-4)'
    )
    
    parser.add_argument(
        '--skip-existing',
        action='store_true',
        help='Skip steps if output already exists'
    )

    parser.add_argument(
        '--url',
        type=str,
        help='Scrape a single Njuskalo search URL with filters already applied (skips category tree scrape)'
    )

    parser.add_argument(
        '--run',
        type=str,
        help='Isolate outputs under backend/runs/<name>/ for separate filter fetches'
    )

    parser.add_argument(
        '--polite',
        action='store_true',
        help='Safer scrape pacing for large runs (~300 ads): 1 concurrent, ~2s delay'
    )
    parser.add_argument(
        '--concurrency',
        type=int,
        default=None,
        help='Max parallel ad downloads (scrape step only)'
    )
    parser.add_argument(
        '--delay',
        type=float,
        default=None,
        help='Seconds between ad request starts (scrape step only)'
    )
    parser.add_argument(
        '--page-delay',
        type=float,
        default=None,
        help='Seconds between search result pages (scrape step only)'
    )
    parser.add_argument(
        '--local-only',
        action='store_true',
        help='Never use proxies during scrape (local IP only)'
    )
    parser.add_argument(
        '--skip-existing-html',
        action='store_true',
        help='Skip ads that already have HTML saved (resume without refetching)'
    )
    
    args = parser.parse_args()
    
    # Create pipeline runner
    runner = PipelineRunner(
        skip_existing=args.skip_existing,
        custom_url=args.url,
        run_name=args.run,
        polite=args.polite,
        concurrency=args.concurrency,
        delay=args.delay,
        page_delay=args.page_delay,
        local_only=args.local_only,
        skip_existing_html=args.skip_existing_html,
    )
    
    try:
        if args.step:
            # Run single step
            success = runner.run_single_step(args.step)
        else:
            # Run full pipeline
            success = runner.run_full_pipeline()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logging.warning("🛑 Pipeline interrupted by user")
        sys.exit(130)
    except Exception as e:
        logging.error(f"💥 Pipeline crashed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
