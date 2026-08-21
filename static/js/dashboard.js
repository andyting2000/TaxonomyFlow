// static/js/dashboard.js - Main Dashboard Controller

import { APIClient } from './api.js';
import { UIManager } from './ui-manager.js';
import { TaxonomySearch } from './taxonomy-search.js';
import { ProgressTracker } from './progress-tracker.js';
import { NotificationManager } from './notifications.js';
import { DataManager } from './data-manager.js';
import { TemplateReviewManager } from './template-review.js';

class XBRLDashboard {
    constructor() {
        // Initialize modules
        this.api = new APIClient();
        this.ui = new UIManager();
        this.notifications = new NotificationManager();
        this.dataManager = new DataManager(this.api, this.notifications);
        this.progressTracker = new ProgressTracker();
        this.templateReview = new TemplateReviewManager(this.api);

        // Initialize taxonomy search with callback
        this.taxonomySearch = new TaxonomySearch(
            this.api,
            (itemId, tagId, tagLabel) => this.onTaxonomyTagSelected(itemId, tagId, tagLabel)
        );

        // Status polling
        this.statusPollingInterval = null;

        // Make template review available globally for onclick handlers
        window.templateReview = this.templateReview;

        this.init();
    }

    async init() {
        console.log('🚀 Initializing Enhanced XBRL Dashboard');

        try {
            // Initialize event listeners
            this.initEventListeners();
            console.log('✅ Event listeners initialized');

            // Load initial data
            await this.loadDashboardStats();
            console.log('✅ Dashboard stats loaded');

            await this.loadJobs();
            console.log('✅ Jobs loaded');

            // Start status polling for processing jobs
            this.startStatusPolling();
            console.log('✅ Status polling started');

            console.log('✅ Dashboard initialization complete');
        } catch (error) {
            console.error('❌ Dashboard initialization failed:', error);
            this.notifications.error('Dashboard initialization failed. Please refresh the page.', 10000);
        }
    }

    initEventListeners() {
        // Upload modal
        document.getElementById('upload-btn').addEventListener('click', () => this.openUploadModal());
        document.getElementById('get-started-btn').addEventListener('click', () => this.openUploadModal());
        document.getElementById('cancel-upload-btn').addEventListener('click', () => this.closeUploadModal());
        document.getElementById('upload-form').addEventListener('submit', (e) => this.handleUpload(e));

        // Action buttons
        document.getElementById('refresh-btn').addEventListener('click', () => this.refreshData());
        document.getElementById('download-btn').addEventListener('click', () => this.downloadXBRL());
        document.getElementById('save-btn').addEventListener('click', () => this.saveChanges());

        // Modal backdrop click
        document.getElementById('upload-modal').addEventListener('click', (e) => {
            if (e.target.id === 'upload-modal') this.closeUploadModal();
        });

        // Delegate event handlers for dynamic elements
        document.addEventListener('click', (e) => {
            // Job card clicks
            if (e.target.closest('.job-card')) {
                const jobCard = e.target.closest('.job-card');
                const jobId = parseInt(jobCard.dataset.jobId);
                this.selectJob(jobId);
            }

            // Pagination buttons
            if (e.target.closest('.pagination-btn')) {
                const pageNumber = parseInt(e.target.closest('.pagination-btn').dataset.page);
                this.goToPage(pageNumber);
            }

            // Delete buttons
            if (e.target.closest('.delete-btn')) {
                const row = e.target.closest('.form-row');
                const itemId = row.dataset.itemId;
                this.deleteRow(itemId);
            }
        });

        // Track changes on form inputs
        document.addEventListener('change', (e) => {
            if (e.target.closest('.form-row') && e.target.dataset.field) {
                const row = e.target.closest('.form-row');
                const itemId = row.dataset.itemId;
                this.trackChange(e.target, itemId);
            }
        });
    }

    // Dashboard Stats
    async loadDashboardStats() {
        try {
            const stats = await this.api.getDashboardStats();
            this.ui.renderDashboardStats(stats);
        } catch (error) {
            console.error('Failed to load dashboard stats:', error);
        }
    }

    // Jobs Management
    async loadJobs() {
        try {
            const jobs = await this.api.getJobs();
            this.ui.renderJobsList(jobs, this.dataManager.currentJob?.id);
        } catch (error) {
            console.error('Failed to load jobs:', error);
            this.notifications.error('Failed to load jobs');
        }
    }

    async selectJob(jobId) {
        try {
            const job = await this.dataManager.loadJob(jobId);

            // Update UI
            this.updateJobSelection(job);

            // Load job data
            if (job.status === 'PROCESSING') {
                this.showProcessingState();
                this.progressTracker.showProgress(jobId, job.company_name);
            } else {
                this.progressTracker.hideProgress();

                // Initialize template review for this job
                await this.templateReview.initialize(jobId);

                // Also load old-style review (for backward compatibility)
                await this.loadJobDataByPages();
            }

            this.notifications.success(`Selected: ${job.company_name}`, 2000);

        } catch (error) {
            console.error('Failed to select job:', error);
            this.notifications.error('Failed to load job');
        }
    }

    updateJobSelection(job) {
        this.ui.updateHeader(`Reviewing: ${job.company_name}`);
        this.ui.showJobContent();
        this.updateDownloadButton();

        // Reload jobs list to update active state
        this.loadJobs();
    }

    showProcessingState() {
        this.ui.showLoading('Processing PDF...');
        this.ui.hideSection('pagination-controls');
        this.ui.hideSection('save-section');
    }

    // Load job data organized by pages
    async loadJobDataByPages() {
        try {
            // Get pages
            await this.dataManager.loadPages();

            if (this.dataManager.totalPages === 0) {
                this.showNoDataMessage();
                return;
            }

            // Load extracted data for current page
            await this.loadCurrentPageData();

            // Setup pagination
            this.ui.renderPagination(
                this.dataManager.currentPageNumber,
                this.dataManager.totalPages
            );

            // Show sections
            this.ui.showSection('save-section');

        } catch (error) {
            console.error('Failed to load job data:', error);
            this.notifications.error('Failed to load page data');
        }
    }

    async loadCurrentPageData() {
        try {
            this.ui.showLoading();

            // Load data from data manager
            const { items, total } = await this.dataManager.loadCurrentPageData();

            // Get page image URL
            const pageImageUrl = this.dataManager.getCurrentPageImageUrl();

            // Render page info
            this.ui.renderPageInfo(
                this.dataManager.currentPageNumber,
                this.dataManager.totalPages,
                items.length,
                pageImageUrl,
                this.dataManager.currentJob.id
            );

            // Render data table
            this.ui.renderDataTable(items);

            // Initialize taxonomy searches
            this.taxonomySearch.initializeSearchInputs();

            // Update counters
            this.updateReviewCount();
            this.updateDownloadButton();

            // Re-bind dynamic buttons
            this.bindPageButtons();

        } catch (error) {
            console.error('Failed to load current page data:', error);
            this.notifications.error('Failed to load page data');
        }
    }

    bindPageButtons() {
        // Add item button
        const addBtn = document.getElementById('add-item-btn');
        if (addBtn) {
            addBtn.addEventListener('click', () => this.addNewItem());
        }

        // Toggle image button
        const toggleBtn = document.getElementById('toggle-image-btn');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => this.togglePageImage());
        }
    }

    showNoDataMessage() {
        this.ui.hideLoading();
        const tbody = document.getElementById('data-table-body');
        tbody.innerHTML = `
            <tr>
                <td colspan="6" class="px-6 py-12 text-center text-gray-500">
                    <div class="text-6xl mb-4">📊</div>
                    <p class="text-lg font-medium">No extracted data found</p>
                    <p class="text-sm">The AI processing didn't extract any financial data from this PDF</p>
                </td>
            </tr>
        `;
    }

    // Navigation
    async goToPage(pageNumber) {
        if (this.dataManager.goToPage(pageNumber)) {
            await this.loadCurrentPageData();
            this.ui.renderPagination(
                this.dataManager.currentPageNumber,
                this.dataManager.totalPages
            );
        }
    }

    // Data Management
    addNewItem() {
        const tbody = document.getElementById('data-table-body');
        const newItemId = 'new_' + Date.now();

        // Get current year
        const currentYear = this.dataManager.currentJob?.financial_year_end
            ? new Date(this.dataManager.currentJob.financial_year_end).getFullYear()
            : new Date().getFullYear();

        const newRowHtml = this.createNewItemRow(newItemId, currentYear);
        tbody.insertAdjacentHTML('beforeend', newRowHtml);

        // Initialize taxonomy search for the new row
        this.taxonomySearch.initializeSearchInputs();

        // Focus on the first input
        const newRow = tbody.querySelector(`[data-item-id="${newItemId}"]`);
        const firstInput = newRow.querySelector('input[data-field="extracted_label"]');
        firstInput.focus();

        // Track change
        this.dataManager.trackChange(newItemId);
        this.ui.showChangesIndicator();

        this.notifications.success('New item added. Fill in the details and save.', 3000);
    }

    createNewItemRow(itemId, currentYear) {
        return `
            <tr class="form-row group hover:bg-gray-50 transition-colors bg-green-50 border-2 border-green-200" data-item-id="${itemId}" data-is-new="true">
                <td class="px-6 py-4 whitespace-nowrap">
                    <input type="number" 
                        class="w-20 px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500"
                        value="${currentYear}" 
                        placeholder="YYYY"
                        min="1900"
                        max="2100"
                        data-field="financial_year">
                </td>
                <td class="px-6 py-4">
                    <input type="text" 
                        class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500"
                        placeholder="Enter financial label..." 
                        data-field="extracted_label">
                </td>
                <td class="px-6 py-4">
                    <input type="text" 
                        class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono bg-gray-50 focus:ring-2 focus:ring-green-500 focus:border-green-500"
                        placeholder="Enter value..."
                        data-field="extracted_value">
                </td>
                <td class="px-6 py-4">
                    <div class="taxonomy-search-container relative">
                        <input type="text" 
                            class="taxonomy-search-input w-full px-4 py-3 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500 transition-all"
                            placeholder="🔍 Search MBRS tags..."
                            data-field="confirmed_tag_id"
                            data-tag-id="">
                        <div class="taxonomy-dropdown absolute top-full left-0 right-0 hidden bg-white border border-gray-300 rounded-b-lg shadow-lg z-50 max-h-60 overflow-y-auto"></div>
                    </div>
                </td>
                <td class="px-6 py-4 text-center">
                    <label class="inline-flex items-center">
                        <input type="checkbox" 
                            class="w-5 h-5 text-green-600 bg-gray-100 border-gray-300 rounded focus:ring-green-500 focus:ring-2"
                            data-field="is_reviewed">
                        <span class="ml-2 text-sm text-gray-600 reviewed-label">Pending</span>
                    </label>
                </td>
                <td class="px-6 py-4 text-center">
                    <button type="button" class="delete-btn p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z"/>
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"/>
                        </svg>
                    </button>
                </td>
            </tr>
        `;
    }

    deleteRow(itemId) {
        if (!confirm('Are you sure you want to delete this item?')) {
            return;
        }

        const row = document.querySelector(`[data-item-id="${itemId}"]`);
        if (!row) return;

        const isNew = row.dataset.isNew === 'true';

        if (isNew) {
            row.remove();
            this.dataManager.pendingChanges.delete(itemId);
            this.notifications.info('New item removed');
        } else {
            row.style.opacity = '0.5';
            row.style.pointerEvents = 'none';
            this.dataManager.trackChange(itemId);
            this.ui.showChangesIndicator();
            this.notifications.warning('Item marked for deletion. Click Save to confirm.');
        }

        this.updateReviewCount();
        this.updateDownloadButton();
    }

    trackChange(element, itemId) {
        this.dataManager.trackChange(itemId);
        this.ui.showChangesIndicator();

        // Update reviewed status label if checkbox
        if (element.dataset.field === 'is_reviewed') {
            const row = element.closest('.form-row');
            const label = row.querySelector('.reviewed-label');
            if (label) {
                label.textContent = element.checked ? '✅ Reviewed' : '⏳ Pending';
            }
            this.updateReviewCount();
        }

        this.updateDownloadButton();
    }

    onTaxonomyTagSelected(itemId, tagId, tagLabel) {
        this.dataManager.trackChange(itemId);
        this.ui.showChangesIndicator();
        this.notifications.success(`Selected: ${tagLabel}`, 2000);
    }

    async saveChanges() {
        if (!this.dataManager.hasPendingChanges()) {
            this.notifications.info('No changes to save');
            return;
        }

        try {
            const saveBtn = document.getElementById('save-btn');
            const originalHTML = saveBtn.innerHTML;

            saveBtn.innerHTML = `
                <div class="loading-spinner mr-2"></div>
                Saving...
            `;
            saveBtn.disabled = true;

            // Save changes
            const result = await this.dataManager.saveChanges();

            this.ui.hideChangesIndicator();
            this.notifications.success(`Successfully saved ${result.count} changes`);

            // Reload current page data
            await this.loadCurrentPageData();

            // Reset button
            saveBtn.innerHTML = originalHTML;
            saveBtn.disabled = false;

        } catch (error) {
            console.error('Save failed:', error);
            this.notifications.error(`Save failed: ${error.message}`);

            // Reset button
            const saveBtn = document.getElementById('save-btn');
            saveBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
                <span>Save Changes</span>
            `;
            saveBtn.disabled = false;
        }
    }

    // UI Updates
    updateReviewCount() {
        const stats = this.dataManager.getReviewStats();
        this.ui.updateReviewCount(stats.reviewed, stats.total);
    }

    updateDownloadButton() {
        const stats = this.dataManager.getReviewStats();
        // Always allow attempting download once a job is selected.
        const enabled = !!this.dataManager.currentJob;
        const title = stats.reviewedWithTags > 0
            ? `Download XBRL with ${stats.reviewedWithTags} reviewed items`
            : 'Download XBRL (will auto-save template inputs first)';

        this.ui.updateDownloadButton(enabled, title);
    }

    togglePageImage() {
        const container = document.getElementById('page-image-container');
        const toggleBtn = document.getElementById('toggle-image-btn');
        const toggleText = toggleBtn.querySelector('.toggle-text');

        if (container.style.display === 'none') {
            container.style.display = 'block';
            toggleText.textContent = 'Hide Image';
        } else {
            container.style.display = 'none';
            toggleText.textContent = 'Show Image';
        }
    }

    // Upload Modal
    openUploadModal() {
        const modal = document.getElementById('upload-modal');
        modal.classList.remove('hidden');
        setTimeout(() => {
            modal.classList.remove('opacity-0');
            modal.querySelector('.modal-content').classList.remove('scale-95');
        }, 10);
    }

    closeUploadModal() {
        const modal = document.getElementById('upload-modal');
        modal.classList.add('opacity-0');
        modal.querySelector('.modal-content').classList.add('scale-95');
        setTimeout(() => {
            modal.classList.add('hidden');
            document.getElementById('upload-form').reset();
        }, 300);
    }

    async handleUpload(e) {
        e.preventDefault();

        const form = e.target;
        const formData = new FormData(form);

        const submitBtn = document.getElementById('submit-upload-btn');
        const uploadText = submitBtn.querySelector('.upload-text');
        const uploadSpinner = submitBtn.querySelector('.upload-spinner');

        try {
            uploadText.classList.add('hidden');
            uploadSpinner.classList.remove('hidden');
            submitBtn.disabled = true;

            const job = await this.api.uploadFile(formData);

            this.notifications.success('File uploaded successfully! Processing started.');
            this.closeUploadModal();

            // Show progress tracker
            this.progressTracker.showProgress(job.id, job.company_name);

            // Refresh data
            await this.loadJobs();
            await this.loadDashboardStats();

            // Select the new job
            await this.selectJob(job.id);

        } catch (error) {
            console.error('Upload failed:', error);
            this.notifications.error(`Upload failed: ${error.message}`);
        } finally {
            uploadText.classList.remove('hidden');
            uploadSpinner.classList.add('hidden');
            submitBtn.disabled = false;
        }
    }

    // XBRL Download
    async downloadXBRL() {
        if (!this.dataManager.currentJob) return;

        try {
            const downloadBtn = document.getElementById('download-btn');
            const originalHTML = downloadBtn.innerHTML;
            let proceedDownload = true;

            // Persist template inputs before generating downloadable XBRL.
            if (this.templateReview && this.templateReview.currentJobId) {
                downloadBtn.innerHTML = `
                    <div class="loading-spinner mr-2"></div>
                    Saving...
                `;
                downloadBtn.disabled = true;

                const saved = await this.templateReview.saveChanges();
                if (!saved) {
                    throw new Error('Please save template changes first before downloading.');
                }
            }

            // Check validation first
            downloadBtn.innerHTML = `
                <div class="loading-spinner mr-2"></div>
                Validating...
            `;
            downloadBtn.disabled = true;

            let validation = null;
            try {
                validation = await this.api.validateXBRL(this.dataManager.currentJob.id);
            } catch (validationError) {
                console.warn('Validation endpoint failed, continuing with download:', validationError);
            }

            // If there are missing required fields, show confirmation dialog
            if (validation && !validation.is_valid && validation.missing_required_fields && validation.missing_required_fields.length > 0) {
                const missingCount = validation.missing_required_fields.length;
                const missingList = validation.missing_required_fields.slice(0, 5).map(f => `  • ${f.statement_type}: ${f.label}`).join('\n');
                const moreSuffix = validation.missing_required_fields.length > 5 ? `\n  ... and ${validation.missing_required_fields.length - 5} more` : '';

                const confirmed = confirm(
                    `⚠️ Validation Warning\n\n` +
                    `There are ${missingCount} required fields not filled in:\n\n` +
                    `${missingList}${moreSuffix}\n\n` +
                    `Do you want to download anyway?\n\n` +
                    `Note: The XBRL file may be incomplete.`
                );

                if (!confirmed) {
                    proceedDownload = false;
                }
            }

            if (!proceedDownload) {
                downloadBtn.innerHTML = originalHTML;
                downloadBtn.disabled = false;
                return;
            }

            // Proceed with download
            downloadBtn.innerHTML = `
                <div class="loading-spinner mr-2"></div>
                Generating...
            `;

            const url = `${this.api.getXBRLDownloadURL(this.dataManager.currentJob.id)}?force=true`;
            const response = await fetch(url);

            if (!response.ok) {
                let detail = `HTTP ${response.status}`;
                try {
                    const errorJson = await response.json();
                    detail = errorJson.detail || errorJson.error || detail;
                } catch (e) {
                    // Keep fallback HTTP status
                }
                throw new Error(detail);
            }

            const blob = await response.blob();
            const downloadUrl = window.URL.createObjectURL(blob);

            const link = document.createElement('a');
            link.href = downloadUrl;
            link.download = `${this.dataManager.currentJob.company_name.replace(/\s+/g, '_')}_MBRS.zip`;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);

            window.URL.revokeObjectURL(downloadUrl);

            this.notifications.success('XBRL file downloaded successfully!');

            setTimeout(() => {
                downloadBtn.innerHTML = originalHTML;
                downloadBtn.disabled = false;
            }, 2000);

        } catch (error) {
            console.error('Download failed:', error);
            this.notifications.error('Download failed: ' + error.message);

            const downloadBtn = document.getElementById('download-btn');
            downloadBtn.innerHTML = `
                <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clip-rule="evenodd" />
                </svg>
                <span>Download XBRL</span>
            `;
            downloadBtn.disabled = false;
        }
    }

    // Status Polling
    startStatusPolling() {
        this.statusPollingInterval = setInterval(async () => {
            await this.checkProcessingJobs();
        }, 3000);
    }

    async checkProcessingJobs() {
        try {
            const jobs = await this.api.getProcessingJobs();
            let currentJobUpdated = false;
            const currentJobId = this.dataManager.currentJob?.id;
            const currentJobWasProcessing = this.dataManager.currentJob?.status === 'PROCESSING';

            console.log(`Polling: Found ${jobs.length} processing jobs`);

            jobs.forEach(job => {
                console.log(`Job ${job.job_id}: ${job.progress}% - ${job.status}`);

                // Check if current job status changed from PROCESSING
                if (this.dataManager.currentJob &&
                    this.dataManager.currentJob.id === job.job_id &&
                    this.dataManager.currentJob.status === 'PROCESSING' &&
                    job.status !== 'PROCESSING') {
                    currentJobUpdated = true;
                    console.log(`Job ${job.job_id} status changed from PROCESSING to ${job.status}`);
                }

                // Update progress tracker for current job
                if (this.dataManager.currentJob && this.dataManager.currentJob.id === job.job_id) {
                    const progress = job.progress || 0;
                    console.log(`Updating progress tracker: ${progress}%`);
                    this.progressTracker.updateProgress(progress, job.status);
                }
            });

            // Also poll the current job directly so we don't miss the final REVIEW transition
            // when it drops out of the "processing jobs" list before the UI refreshes.
            if (currentJobId && currentJobWasProcessing) {
                const currentStatus = await this.api.getJobStatus(currentJobId);
                console.log(
                    `Current job ${currentJobId} direct status: ${currentStatus.progress}% - ${currentStatus.status}`
                );

                this.progressTracker.updateProgress(
                    currentStatus.progress || 0,
                    currentStatus.status
                );

                if (currentStatus.status !== 'PROCESSING') {
                    currentJobUpdated = true;
                    console.log(
                        `Job ${currentJobId} status changed from PROCESSING to ${currentStatus.status} via direct status poll`
                    );
                }
            }

            // Auto-update current job if processing completed
            if (currentJobUpdated) {
                console.log('Processing completed! Auto-refreshing...');
                this.notifications.success('Processing completed! Reloading page data...', 3000);
                this.progressTracker.hideProgress();

                // Reload job and job list immediately
                setTimeout(async () => {
                    await this.loadDashboardStats(); // Update stats
                    await this.loadJobs(); // Update job list
                    await this.selectJob(this.dataManager.currentJob.id); // Reload current job
                }, 1000); // Reduced delay from 1500ms to 1000ms for faster response
            }

        } catch (error) {
            console.error('Status polling failed:', error);
        }
    }

    // Utility
    async refreshData() {
        try {
            await Promise.all([
                this.loadJobs(),
                this.loadDashboardStats()
            ]);

            if (this.dataManager.currentJob) {
                await this.loadJobDataByPages();
            }

            this.notifications.success('Data refreshed', 2000);

        } catch (error) {
            console.error('Refresh failed:', error);
            this.notifications.error('Refresh failed');
        }
    }

    // Cleanup
    destroy() {
        if (this.statusPollingInterval) {
            clearInterval(this.statusPollingInterval);
        }
        this.progressTracker.cleanup();
    }
}

// Initialize dashboard when DOM is loaded
let dashboard;
document.addEventListener('DOMContentLoaded', () => {
    dashboard = new XBRLDashboard();
});

// Export for testing or external use
export { XBRLDashboard };
