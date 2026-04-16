// Global utility functions

// Check if user is logged in and update nav
async function updateNav() {
    try {
        const response = await fetch('/check-session');
        const data = await response.json();
        const navMenu = document.getElementById('navMenu');
        
        if (data.authenticated) {
            navMenu.innerHTML = `
                <span>Welcome, ${data.user.username}</span>
                <a href="#" onclick="logout()">Logout</a>
            `;
        } else {
            navMenu.innerHTML = `
                <a href="/login">Login</a>
                <a href="/register">Register</a>
            `;
        }
    } catch (error) {
        console.error('Error updating nav:', error);
    }
}

// Logout function
async function logout() {
    await fetch('/logout', { method: 'POST' });
    window.location.href = '/login';
}

// Run on every page
document.addEventListener('DOMContentLoaded', updateNav);
