const logoutButton = document.querySelector('.logout-button');

// Click event listener
logoutButton.addEventListener('click', function(event) {
    event.preventDefault(); // Prevent default link behavior
    
    initiateLogout();
});

// Logout function
function initiateLogout() {
    const url = 'https://accounts.spotify.com/en/logout';
    const spotifyLogoutWindow = window.open(url, 'Spotify Logout', 'width=700,height=500,top=40,left=40');

    setTimeout(() => {
        spotifyLogoutWindow.close();
        window.location.replace('/'); // Redirect to home page after closing
    }, 500); // Close window after 0.5 secs
}