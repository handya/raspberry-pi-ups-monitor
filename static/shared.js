function timeAgo(timestamp) {
    const now = new Date();
    const time = new Date(timestamp);
    const diffMs = now - time;
    const diffSec = Math.floor(diffMs / 1000);
    const diffMin = Math.floor(diffSec / 60);
    const diffHr = Math.floor(diffMin / 60);
    const diffDay = Math.floor(diffHr / 24);

    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    return `${diffDay}d ago`;
}

function formatEventName(name) {
    const SPECIAL_WORDS = ['UPS', 'API', 'CPU'];
    return name.split('_').map(word => {
        const upper = word.toUpperCase();
        if (SPECIAL_WORDS.includes(upper)) return upper;
        return word.charAt(0).toUpperCase() + word.slice(1);
    }).join(' ');
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const sec = Math.floor(seconds % 60);
    const min = Math.floor(seconds / 60);
    return `${min}:${sec.toString().padStart(2, '0')}`;
}

function getIndicatorClass(event, state) {
    const goodStates = ['ups_connected', 'on_ups', 'monitor_started'];
    const faultStates = ['ups_fault', 'low_battery', 'on_battery', 'on_bypass', 'alarm'];

    if (goodStates.includes(event)) {
        return state === 'ON' ? 'indicator-on' : 'indicator-fault';
    }

    if (faultStates.includes(event)) {
        return state === 'ON' ? 'indicator-fault' : 'indicator-on';
    }

    // fallback for unknown events
    return 'indicator-off';
}
