import os
import requests
import random
from flask import Flask, render_template, redirect, request, session, url_for, flash
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Spotify API credentials
CLIENT_ID = '2e2fd139796d4aab89e60b40777567d9'
CLIENT_SECRET = '93f996cf889542fe9dec5f8bf53fccbc'
REDIRECT_URI = 'http://localhost:5000/callback'
SCOPE = 'playlist-modify-public playlist-modify-private user-read-private'

@app.route('/')
def home():
    return '<a href="/login">Login with Spotify:</a>'

@app.route('/login')
def login():
    auth_url = 'https://accounts.spotify.com/authorize?' + urlencode({
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'scope': SCOPE,
        'redirect_uri': REDIRECT_URI,
    })
    return redirect(auth_url)

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

@app.route('/create_playlist/<playlist_id>', methods=['GET', 'POST'])
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
            flash("Failed to fetch audio features.")
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))

        avg_features = calculate_avg_features(audio_features)
        recommendations = get_recommendations(headers, random_tracks, avg_features, track_ids, num_songs)

        track_infos = [{
            'id': item['track']['id'],
            'name': item['track']['name'],
            'artists': ', '.join(artist['name'] for artist in item['track']['artists']),
            'image': item['track']['album']['images'][0]['url'] if item['track']['album']['images'] else None,
            'duration': item['track']['duration_ms']
        } for item in recommendations['items'] if item['track']]

        if not recommendations:
            flash("Error fetching recommendations or no recommendations found.")
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))

        track_uris = [f'spotify:track:{track["id"]}' for track in recommendations]
        success, new_playlist_id = create_playlist(access_token, user_id, playlist_name, track_uris)

        if success:
            flash(f'Playlist "{playlist_name}" created successfully with ID: {new_playlist_id}')
            return render_template('display.html', playlist_name=playlist_name, tracks=recommendations, track_infos = track_infos)
        else:
            flash('Failed to create playlist.')
            return redirect(url_for('playlistInfo', playlist_id=playlist_id))

    return render_template('playlistInfo.html', playlist_id=playlist_id)

def create_playlist(access_token, user_id, playlist_name, track_uris):
    create_playlist_url = f'https://api.spotify.com/v1/users/{user_id}/playlists'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        'name': playlist_name,
        'public': False
    }
    response = requests.post(create_playlist_url, headers=headers, json=data)
    
    if response.status_code == 201:
        response_data = response.json()
        playlist_id = response_data['id']
        add_tracks_url = f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks'
        data = {'uris': track_uris}
        response = requests.post(add_tracks_url, headers=headers, json=data)

        # Debugging print statements
        print(f"Response Status Code (Add Tracks): {response.status_code}")
        print(f"Response JSON (Add Tracks): {response.json()}")

        if response.status_code == 201 or response.status_code == 200:
            print("Success creating playlist!") # Debug print
            return True, playlist_id
        else:
            print(f"Error adding tracks: {response.json()}")  # Debug print
            return False, None
    else:
        print(f"Error creating playlist: {response.json()}")  # Debug print
        return False, None

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
        
        if recommendations_response.status_code != 200:
            return None

        recommendations_data = recommendations_response.json()
        new_recommendations = [track for track in recommendations_data['tracks'] if track['id'] not in track_ids and track['id'] not in [rec['id'] for rec in unique_recommendations]]

        unique_recommendations.extend(new_recommendations)

        if len(unique_recommendations) > limit:
            unique_recommendations = unique_recommendations[:limit]

        attempts += 1

    return unique_recommendations

@app.template_filter('format_duration')
def format_duration(value):
    return f'{value:02}'

if __name__ == '__main__':
    app.run(debug=True)