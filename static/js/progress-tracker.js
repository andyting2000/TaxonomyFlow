// static/js/progress-tracker.js - Progress Tracking UI

export class ProgressTracker {
    constructor() {
        this.currentJobId = null;
        this.isVisible = false;
        this.startTime = null;
        this.timerInterval = null;
        this.createProgressElement();
    }

    createProgressElement() {
        const progressHTML = `
            <div id="progress-tracker" class="fixed bottom-6 right-6 hidden bg-white rounded-lg shadow-2xl border border-gray-200 p-4 w-80 transform transition-all duration-300 z-50 hover:shadow-3xl" style="transform: translateY(calc(100% + 1.5rem));">
                <div class="flex items-center justify-between mb-3">
                    <h4 class="font-semibold text-gray-900">Processing Status</h4>
                    <button id="close-progress" class="text-gray-500 hover:text-gray-700 p-1 rounded">
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path>
                        </svg>
                    </button>
                </div>
                
                <div id="progress-content">
                    <div class="flex items-center space-x-3 mb-3">
                        <div class="loading-spinner"></div>
                        <div>
                            <p class="font-medium text-gray-900" id="progress-company"></p>
                            <p class="text-sm text-gray-600" id="progress-status">Starting processing...</p>
                        </div>
                    </div>
                    
                    <div class="bg-gray-200 rounded-full h-2 mb-2">
                        <div id="progress-bar" class="bg-gradient-to-r from-blue-500 to-blue-600 h-2 rounded-full transition-all duration-500" style="width: 0%"></div>
                    </div>
                    
                    <div class="flex justify-between text-xs text-gray-500">
                        <span id="progress-percentage">0%</span>
                        <span id="progress-time">Starting...</span>
                    </div>
                </div>
            </div>
        `;
        
        document.body.insertAdjacentHTML('beforeend', progressHTML);
        
        // Add event listeners
        document.getElementById('close-progress').addEventListener('click', () => {
            this.hideProgress();
        });
    }

    showProgress(jobId, companyName, startTimer = true) {
        this.currentJobId = jobId;
        this.isVisible = true;
        
        const tracker = document.getElementById('progress-tracker');
        const companyEl = document.getElementById('progress-company');
        const statusEl = document.getElementById('progress-status');
        const progressBar = document.getElementById('progress-bar');
        const percentageEl = document.getElementById('progress-percentage');
        
        // Update content
        companyEl.textContent = companyName;
        statusEl.textContent = 'Processing PDF...';
        progressBar.style.width = '0%';
        percentageEl.textContent = '0%';
        
        if (startTimer) {
            this.startTime = Date.now();
        }
        this.updateTimer();
        
        // Show tracker
        tracker.classList.remove('hidden');
        requestAnimationFrame(() => {
            tracker.style.transform = 'translateY(0)';
        });
        
        // Start timer
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
        }
        this.timerInterval = setInterval(() => {
            this.updateTimer();
        }, 1000);
    }

    updateProgress(percentage, status) {
        if (!this.isVisible) return;
        
        const statusEl = document.getElementById('progress-status');
        const progressBar = document.getElementById('progress-bar');
        const percentageEl = document.getElementById('progress-percentage');
        
        if (statusEl) {
            statusEl.textContent = this.getStatusMessage(status);
        }
        
        if (progressBar) {
            progressBar.style.width = `${percentage}%`;
        }
        
        if (percentageEl) {
            percentageEl.textContent = `${percentage}%`;
        }
        
        // Change color based on status
        if (progressBar) {
            if (status === 'ERROR') {
                progressBar.className = 'bg-gradient-to-r from-red-500 to-red-600 h-2 rounded-full transition-all duration-500';
            } else if (percentage === 100) {
                progressBar.className = 'bg-gradient-to-r from-green-500 to-green-600 h-2 rounded-full transition-all duration-500';
            } else {
                progressBar.className = 'bg-gradient-to-r from-blue-500 to-blue-600 h-2 rounded-full transition-all duration-500';
            }
        }
    }

    hideProgress() {
        this.isVisible = false;
        const tracker = document.getElementById('progress-tracker');
        if (tracker) {
            tracker.style.transform = 'translateY(calc(100% + 1.5rem))';
            setTimeout(() => {
                if (!this.isVisible) {
                    tracker.classList.add('hidden');
                }
            }, 300);
        }
        
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
    }

    updateTimer() {
        if (!this.startTime) return;
        
        const elapsed = Math.floor((Date.now() - this.startTime) / 1000);
        const minutes = Math.floor(elapsed / 60);
        const seconds = elapsed % 60;
        
        const timeEl = document.getElementById('progress-time');
        if (timeEl) {
            timeEl.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
        }
    }

    getStatusMessage(status) {
        switch (status) {
            case 'PROCESSING':
                return 'Processing PDF with AI...';
            case 'REVIEW':
                return 'Processing complete!';
            case 'COMPLETED':
                return 'All done!';
            case 'ERROR':
                return 'Processing failed';
            default:
                return 'Processing...';
        }
    }

    cleanup() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
        }
        const tracker = document.getElementById('progress-tracker');
        if (tracker) {
            tracker.remove();
        }
    }
}
