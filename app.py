import os
import time
import logging
import requests
import webbrowser
import random
import spotipy
from base64 import b64encode
from spotipy.oauth2 import SpotifyOAuth
from flask import Flask, render_template, redirect, request, session, url_for, flash, jsonify
from flask_cors import CORS
from urllib.parse import urlencode

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app, resources={r"/*": {"origins": "https://quiet-chamber-15314-d9d157e1046c.herokuapp.com/"}})
app.secret_key = os.urandom(24)

# Spotify API credentials
CLIENT_ID = '2e2fd139796d4aab89e60b40777567d9'
CLIENT_SECRET = '93f996cf889542fe9dec5f8bf53fccbc'
REDIRECT_URI = 'https://quiet-chamber-15314-d9d157e1046c.herokuapp.com/callback'
SCOPE = 'playlist-modify-public playlist-modify-private user-read-private'
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=CLIENT_ID,
                                               client_secret=CLIENT_SECRET,
                                               redirect_uri=REDIRECT_URI,
                                               scope=SCOPE))

@app.route('/')
def home():
    return render_template("index.html")

@app.route('/about')
def about():
    return render_template("about.html")

@app.route('/privacy')
def privacy():
    return render_template("privacy.html")

@app.route('/login')
def login():
    auth_url = 'https://accounts.spotify.com/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'scope': SCOPE,
        'redirect_uri': REDIRECT_URI,
    })
    return redirect(auth_url)

@app.route('/logout')
def logout():
    return render_template('logout.html')

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_url = 'https://accounts.spotify.com/api/token'
    response = requests.post(token_url, data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    })

    response_data = response.json()
    session['access_token'] = response_data['access_token']
    session['refresh_token'] = response_data['refresh_token']

    access_token = response_data['access_token']
    headers = {'Authorization': f'Bearer {access_token}'}
    user_info_response = requests.get('https://api.spotify.com/v1/me', headers=headers)
    user_info = user_info_response.json()
    session['user_id'] = user_info['id']

    return redirect(url_for('playlists'))

@app.route('/playlists', methods=['GET'])
def playlists():
    access_token = session.get('access_token')
    if not access_token:
        return redirect(url_for('login'))

    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get('https://api.spotify.com/v1/me/playlists', headers=headers)

    # Check if the response is successful and contains the expected data
    if response.status_code == 200:
        playlists_data = response.json()
        if 'items' in playlists_data:
            # Extract necessary data, including images
            playlists = [{
                'id': playlist['id'],
                'name': playlist['name'],
                'images': playlist['images']
            } for playlist in playlists_data['items']]
            return render_template('playlists.html', playlists=playlists)
        else:
            flash("Unexpected response format.")
            return redirect(url_for('home'))
    else:
        flash("Failed to fetch playlists.")
        return redirect(url_for('home'))

@app.route('/playlistInfo/<playlist_id>', methods=['GET', 'POST'])
def playlistInfo(playlist_id):
    access_token = session.get('access_token')
    if not access_token:
        return redirect(url_for('login'))

    if request.method == 'POST':
        num_songs = request.form.get('num_songs')
        playlist_name = request.form.get('playlist_name')

        # Proceed with the playlist_tracks logic directly
        if not num_songs:
            num_songs = 10
        else:
            num_songs = int(num_songs)

        if not playlist_name:
            playlist_name = "My Recommendation Playlist"
        else:
            playlist_name = str(playlist_name)

        headers = {'Authorization': f'Bearer {access_token}'}
        try:
            # Get playlist tracks
            response = requests.get(f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks', headers=headers)
            response.raise_for_status()
            tracks_data = response.json()
        except requests.RequestException as e:
            print(f"Error fetching playlist tracks: {e}")
            flash("Failed to fetch playlist tracks.")
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))

        user_id = session.get('user_id')
        track_ids = [item['track']['id'] for item in tracks_data['items'] if item['track'] and item['track']['id']]

        if not track_ids:
            flash("No tracks found in the playlist.")
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))
        
        # Filter out None values from track_ids
        track_ids = list(filter(None, track_ids))

        # Get 5 random tracks to use as seeds
        random_tracks = random.sample(track_ids, 5) if len(track_ids) >= 5 else track_ids
        
        try:
            audio_features_response = requests.get('https://api.spotify.com/v1/audio-features', headers=headers, params={'ids': ','.join(track_ids)})
            audio_features_response.raise_for_status()
            audio_features = audio_features_response.json()['audio_features']
        except requests.RequestException as e:
            print(f"Error fetching audio features: {e}")
            flash("Failed to fetch audio features.")
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))

        avg_features = calculate_avg_features(audio_features)
        recommendations = get_recommendations(headers, random_tracks, avg_features, track_ids, num_songs)

        if not recommendations:
            print(f"Error fetching recs: ")
            flash("Error fetching recommendations or no recommendations found.")
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))

        print(f"recs")
        
        track_infos = recommendations
        print(track_infos)

        track_uris = [f'spotify:track:{track["id"]}' for track in recommendations]

        session['access_token'] = access_token
        session['user_id'] = user_id
        session['playlist_name'] = playlist_name
        session['track_uris'] = track_uris

        return render_template('display.html', playlist_name=playlist_name, track_infos = track_infos, 
                               playlist_id = playlist_id, track_uris = track_uris)
    
    return render_template('playlistInfo.html', playlist_id=playlist_id)
    
@app.route('/create_playlist/<playlist_id>', methods=['POST'])
def create_playlist(playlist_id):
    access_token = session.get('access_token')
    user_id = session.get('user_id')
    playlist_name = session.get('playlist_name')
    track_uris = session.get('track_uris')

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        'name': playlist_name,
        'public': False
    }

    create_playlist_url = f'https://api.spotify.com/v1/users/{user_id}/playlists'
    try:
        response = requests.post(create_playlist_url, headers=headers, json=data)
        response.raise_for_status()  # Raise exception for non-2xx responses

        if response.status_code == 201:
            response_data = response.json()
            new_playlist_id = response_data['id']

            # Add tracks to the new playlist
            add_tracks_url = f'https://api.spotify.com/v1/playlists/{new_playlist_id}/tracks'
            add_tracks_data = {'uris': track_uris}
            add_response = requests.post(add_tracks_url, headers=headers, json=add_tracks_data)
            add_response.raise_for_status()

            return jsonify({'message': f'Playlist "{playlist_name}" created successfully!', 'playlist_id': playlist_id}), 200
        else:
            return jsonify({'error': 'Failed to add tracks to the playlist.'}), 500

    except requests.RequestException as e:
        return jsonify({'error': 'Failed to create playlist.'}), 500


def calculate_avg_features(audio_features):
    num_tracks = len(audio_features)
    avg_features = {
        'danceability': sum(track['danceability'] for track in audio_features) / num_tracks,
        'energy': sum(track['energy'] for track in audio_features) / num_tracks,
        'loudness': sum(track['loudness'] for track in audio_features) / num_tracks,
        'speechiness': sum(track['speechiness'] for track in audio_features) / num_tracks,
        'acousticness': sum(track['acousticness'] for track in audio_features) / num_tracks,
        'instrumentalness': sum(track['instrumentalness'] for track in audio_features) / num_tracks,
        'liveness': sum(track['liveness'] for track in audio_features) / num_tracks,
        'mode': round(sum(track['mode'] for track in audio_features) / num_tracks),
        'valence': sum(track['valence'] for track in audio_features) / num_tracks,
        'tempo': sum(track['tempo'] for track in audio_features) / num_tracks,
    }
    return avg_features

def get_recommendations(headers, random_tracks, avg_features, track_ids, limit):
    unique_recommendations = []
    attempts = 0
    max_attempts = 5  # Limiting the number of attempts to avoid potential infinite loops

    while len(unique_recommendations) < limit and attempts < max_attempts:
        recommendations_response = requests.get(
            'https://api.spotify.com/v1/recommendations',
            headers=headers,
            params={
                'limit': limit,
                'seed_tracks': random_tracks,
                'target_danceability': avg_features['danceability'],
                'target_energy': avg_features['energy'],
                'target_loudness': avg_features['loudness'],
                'target_speechiness': avg_features['speechiness'],
                'target_acousticness': avg_features['acousticness'],
                'target_instrumentalness': avg_features['instrumentalness'],
                'target_liveness': avg_features['liveness'],
                'target_mode': avg_features['mode'],
                'target_valence': avg_features['valence'],
                'target_tempo': avg_features['tempo'],
            }
        )

        if recommendations_response.status_code == 429:  # Rate limit exceeded
                retry_after = int(recommendations_response.headers.get('Retry-After', 1))
                logging.warning(f"Rate limit exceeded. Retrying after {retry_after} seconds")
                time.sleep(retry_after)
                continue
        
        if recommendations_response.status_code != 200:
            return None

        recommendations_data = recommendations_response.json()
        new_recommendations = [
            {
                'id': track['id'],
                'name': track['name'],
                'artists': ', '.join(artist['name'] for artist in track['artists']),
                'image': track['album']['images'][0]['url'] if track['album']['images'] else None,
                'duration': track['duration_ms'],
                'external_urls': track['external_urls']['spotify']  # Spotify external URL
            } 
            for track in recommendations_data['tracks']
            if track['id'] not in track_ids 
            and track['id'] not in [rec['id'] for rec in unique_recommendations]
        ]

        unique_recommendations.extend(new_recommendations)

        if len(unique_recommendations) > limit:
            unique_recommendations = unique_recommendations[:limit]

        attempts += 1

    return unique_recommendations

@app.route('/add_track/<playlist_id>/<track_id>', methods=['POST'])
def add_track(playlist_id, track_id):
    try:
        sp.playlist_add_items(playlist_id, [track_id])
        return jsonify({'message': 'Track added successfully!'}), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500

@app.template_filter('format_duration')
def format_duration(value):
    return f'{value:02}'

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
