import argparse
from datetime import datetime
from utils import BadOptionsError, makedir, convert_to_date, LogDecorator, craigslist_format_to_date, craigslist_format_to_datetime

from google_utils import get_blob
from ffmpeg_utils import concat_videos
import os
from async_utils import handle_requests



# New Alg --
# Stitch request comes in...
# Scrape:
#   Scrape in accordance to request -- city/cities, word count, date, urls?
#   Store scraped ads in bucket dir hashed by request name
#   Return paths to ads and other info to stitcher
# Poem:
#   Take all ads and create poems
#   Store poems in temp bucket for request as well
#   Return paths to all videos
# Stitch:
#   Validate
#   Stitch
#   Upload


# Q: Maybe ad scraping should be done per stitch request

# TODO: Handle more use cases
# TODO: Handle YOUTUBE uploads
# TODO: Allow title, description and other features to be input
# TODO: Make interceding clips of something..
# TODO: Progress updates & live logging
# TODO: Search words & prefixes
# TODO: Make poem-maker return JSON of generated video paths
# TODO: Make craigslist-scraper return JSON array of bucket paths
# TODO: Allow min video length & min word count for all-of-day videos
# TODO: Make voice options passable

# CASES:
# Request all-of-day video for DATE:
#   Scrape all of DATE
#   Send all ads from DATE to poem-maker
#   Concat all poems order by datetime
#
# Creepy flag for any video adds voice options & prefixes (change font?)
#
#


CRAIG_THE_POET_BUCKET = 'craig-the-poet'
POEM_DIR = 'poems'
AD_DIR = 'craigslist'

FFMPEG_CONFIG = {'loglevel': 'panic', 'safe': 0, 'hide_banner': None, 'y': None}

CRAIGSLIST_SCRAPER_ENDPOINT = os.environ['CRAIGSLIST_SCRAPER_ENDPOINT']
POEM_MAKER_ENDPOINT = os.environ['POEM_MAKER_ENDPOINT']


def poem_stitcher(cities=None, dont_post_if_runtime_under=None, min_length=None, max_length=None, date=None, all_of_day=False, **kwargs):
    # Toss invalid combinations of args
    if args.all_of_day and (not args.date or not args.cities):
        raise BadOptionsError('Must specify DATE and CITIES when using ALL_OF_DAY flag')

    # Ensure correct typing
    dont_post_if_runtime_under = float(dont_post_if_runtime_under) if dont_post_if_runtime_under else None
    date = convert_to_date(date) if type(date) == str else date if type(date) != None else None

    # TODO Hash args to create the dir
    destination_bucket_dir = 'd'

    ##############
    # SCRAPE ADS #
    ##############

    # Form request list for scrapers
    scraper_request_list = []

    # NOTE: Handled cases: (all-of-day, date, city)
    if all_of_day:
        # Scrape each city for ads from DATE
        for city in cities:
            scraper_request_list.append({
                'method': 'POST',
                'url': CRAIGSLIST_SCRAPER_ENDPOINT,
                'json': {
                    'destination_bucket_dir': destination_bucket_dir,
                    'city': city,
                    'date': f'{date.month}-{date.day}-{date.year}',
                    # TODO: Attach min word count and such here
                }
            })

    # Send requests from list concurrently
    responses = handle_requests(scraper_request_list)

    # Capture all scraped ad bucket paths
    ad_bucket_paths = []
    for response in responses:
        ad_bucket_paths += eval(response.decode('utf-8'))


    ##################
    # GENERATE POEMS #
    ##################

    # Request poem for each scraped ad's blob
    maker_request_list = []

    if all_of_day:
        for ad_bucket_path in ad_bucket_paths:
            maker_request_list.append({
                'method': 'POST',
                'url': POEM_MAKER_ENDPOINT,
                'json': {
                    'bucket_path': ad_bucket_path,
                    'destination_bucket_dir': destination_bucket_dir
                }
            })
    else:
        print('Not yet handling cases other than --all-of-day. Exiting...')
        exit()

    responses = handle_requests(maker_request_list)

    # Capture all videos bucket paths
    poem_bucket_paths = []
    for response in responses:
        video_bucket_paths += eval(response.decode('utf-8'))

    # Grab the blobs
    video_blobs = [get_blob(bucket_path) for bucket_path in video_bucket_paths]

    #########
    # ORDER #
    #########

    # Order the blobs by time of post
    def to_datetime(b):
        # e.g. 2019-12-25T21:27:07-0600
        datetime_string = b.metadata['ad-posted-time'].split('')
        date_string, time_string = datetime_string.split('T')
        year, month, day = date_string.split('-')
        hour, minute, second = time_string.split('-')[0].split(':')
        return datetime.strptime(f'{year}-{month}-{day}-{hour}-{minute}-{second}', "%Y-%m-%d-%H-%M-%S")

    video_blobs = sorted(video_blobs, key=to_datetime)

    ############
    # VALIDATE #
    ############

    # Check current sum of poem run time
    total_runtime = sum(float(blob.metadata['runtime']) for blob in video_blobs)

    if dont_post_if_runtime_under and total_runtime < dont_post_if_runtime_under:
        raise Exception('Minimum runtime length not met. Exiting...')


    ################
    # CONCAT POEMS #
    ################

    # Download all poems that we've selected
    makedir('poems')
    local_poem_filepaths = []
    for i, blob in enumerate(video_blobs):
        local_poem_filepath = f'poems/poem-{i}.mp4'
        blob.download_to_filename(local_poem_filepath)
        local_poem_filepaths += [local_poem_filepath]

    # Concat all the poem into one
    concat_videos(local_poem_filepaths, 'out.mp4', **FFMPEG_CONFIG)

    print('Concatenation complete')

    #####################
    # UPLOAD TO YOUTUBE #
    #####################

    # TODO: In upload process, allow kwargs to set all YT stuff

#    for blob in selected_poem_blobs:
#        blob.metadata = {'used': 'true'}
#        blob.patch()

    pass




if __name__ == '__main__':
    '''
    TODO

    Get modes working for these use cases
        handled
              create & upload video of all ads for the day

        handling
              create & upload video of length > 10min

        unhandled
              create & upload video of length > 10min for given day
              create & upload video with 3 long ads
              create & upload video with 1 long, 1 medium, 1 short, and 1 long ad
              Set ranges for short, medium, and longness (as word count)
    '''


    parser = argparse.ArgumentParser()
    parser.add_argument('--cities', nargs='+')

    parser.add_argument('--all-of-day', action='store_true')

    # AD FILTERS
    parser.add_argument('--date', help='Filter to only posts from this date. Format: mm-dd-yyyy', type=convert_to_date)

    # POEM FILTERS
    parser.add_argument('--dont-post-if-runtime-under', type=float)



    # Min/Max output video length -- time in seconds
    parser.add_argument('--min-length', type=float)
    parser.add_argument('--max-length', type=float)



    args = parser.parse_args()


    poem_stitcher(**vars(args))
