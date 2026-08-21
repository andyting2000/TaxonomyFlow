// static/js/ui-manager.js - UI Rendering and DOM Manipulation

export class UIManager {
    constructor() {
        this.elements = this.cacheElements();
    }

    cacheElements() {
        return {
            // Containers
            jobsList: document.getElementById('jobs-list'),
            contentArea: document.getElementById('content-area'),
            welcomeScreen: document.getElementById('welcome-screen'),
            jobContent: document.getElementById('job-content'),
            dashboardStats: document.getElementById('dashboard-stats'),

            // Header elements
            headerTitle: document.getElementById('header-title'),
            jobCountDisplay: document.getElementById('job-count-display'),

            // Data table
            dataTableBody: document.getElementById('data-table-body'),
            loadingIndicator: document.getElementById('loading-indicator'),
            reviewedCount: document.getElementById('reviewed-count'),
            totalCount: document.getElementById('total-count'),

            // Page info and controls
            pageInfo: document.getElementById('page-info'),
            paginationControls: document.getElementById('pagination-controls'),
            paginationNav: document.getElementById('pagination-nav'),
            itemsInfo: document.getElementById('items-info'),

            // Buttons
            downloadBtn: document.getElementById('download-btn'),
            saveBtn: document.getElementById('save-btn'),
            refreshBtn: document.getElementById('refresh-btn'),
            changesIndicator: document.getElementById('changes-indicator'),

            // Sections
            saveSection: document.getElementById('save-section'),
            pagesSection: document.getElementById('pages-section')
        };
    }

    // Dashboard Stats Rendering
    renderDashboardStats(stats) {
        this.elements.dashboardStats.innerHTML = `
            <div class="bg-gradient-to-br from-blue-50 to-blue-100 p-6 rounded-xl border border-blue-200">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-blue-600 text-sm font-medium">Total Jobs</p>
                        <p class="text-2xl font-bold text-blue-900">${stats.total_jobs}</p>
                    </div>
                    <div class="p-3 bg-blue-500 rounded-lg">
                        <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
                        </svg>
                    </div>
                </div>
            </div>
            
            <div class="bg-gradient-to-br from-green-50 to-green-100 p-6 rounded-xl border border-green-200">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-green-600 text-sm font-medium">Completed</p>
                        <p class="text-2xl font-bold text-green-900">${stats.completed_jobs}</p>
                    </div>
                    <div class="p-3 bg-green-500 rounded-lg">
                        <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"/>
                        </svg>
                    </div>
                </div>
            </div>
            
            <div class="bg-gradient-to-br from-yellow-50 to-yellow-100 p-6 rounded-xl border border-yellow-200">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-yellow-600 text-sm font-medium">Processing</p>
                        <p class="text-2xl font-bold text-yellow-900">${stats.processing_jobs}</p>
                    </div>
                    <div class="p-3 bg-yellow-500 rounded-lg">
                        <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path d="M10 12a2 2 0 100-4 2 2 0 000 4z"/>
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-13a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V5z"/>
                        </svg>
                    </div>
                </div>
            </div>
            
            <div class="bg-gradient-to-br from-purple-50 to-purple-100 p-6 rounded-xl border border-purple-200">
                <div class="flex items-center justify-between">
                    <div>
                        <p class="text-purple-600 text-sm font-medium">Reviewed Items</p>
                        <p class="text-2xl font-bold text-purple-900">${stats.reviewed_items}</p>
                    </div>
                    <div class="p-3 bg-purple-500 rounded-lg">
                        <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"/>
                        </svg>
                    </div>
                </div>
            </div>
        `;
    }

    // Job List Rendering
    renderJobsList(jobs, currentJobId = null) {
        this.elements.jobCountDisplay.textContent = `${jobs.length} total jobs`;

        if (jobs.length === 0) {
            this.elements.jobsList.innerHTML = `
                <div class="text-center p-8">
                    <div class="text-gray-400 text-6xl mb-4">📄</div>
                    <p class="text-gray-400">No jobs yet</p>
                    <p class="text-sm text-gray-500 mt-1">Upload your first PDF to get started</p>
                </div>
            `;
            return;
        }

        this.elements.jobsList.innerHTML = jobs.map(job =>
            this.createJobCard(job, currentJobId)
        ).join('');
    }

    createJobCard(job, currentJobId) {
        const date = new Date(job.uploaded_at).toLocaleDateString();
        const isActive = currentJobId && currentJobId === job.id;

        let statusBadge = '';
        let statusClass = '';

        switch (job.status) {
            case 'COMPLETED':
                statusBadge = '✅ Complete';
                statusClass = 'status-badge';
                break;
            case 'REVIEW':
                statusBadge = '🔍 Review';
                statusClass = 'px-3 py-1 text-xs font-semibold text-blue-100 bg-blue-600/80 rounded-full';
                break;
            case 'PROCESSING':
                statusBadge = '⏳ Processing';
                statusClass = 'status-badge processing';
                break;
            case 'ERROR':
                statusBadge = '❌ Error';
                statusClass = 'status-badge error';
                break;
        }

        return `
            <div class="job-card block p-4 rounded-xl transition-all duration-200 group cursor-pointer ${isActive ? 'bg-gradient-to-r from-blue-600 to-blue-700 shadow-lg scale-105' : 'bg-gray-700/50 hover:bg-gray-600/50 hover:scale-102'
            }" data-job-id="${job.id}">
                <div class="flex justify-between items-start">
                    <div class="flex-1 min-w-0">
                        <p class="font-semibold text-white truncate group-hover:text-blue-200 transition-colors">
                            ${job.company_name}
                        </p>
                        <p class="text-sm mt-1 ${isActive ? 'text-blue-200' : 'text-gray-400'}">
                            FYE: ${date}
                        </p>
                    </div>
                    <div class="ml-3">
                        <span class="${statusClass} px-3 py-1 text-xs font-semibold text-white rounded-full">
                            ${statusBadge}
                        </span>
                    </div>
                </div>
            </div>
        `;
    }

    // Page Info Rendering
    renderPageInfo(pageNumber, totalPages, itemCount, pageImageUrl, jobId) {
        this.elements.pageInfo.innerHTML = `
            <div class="space-y-4">
                <!-- Page Image Section -->
                <div class="bg-white rounded-lg border border-gray-200 p-4">
                    <div class="flex items-center justify-between mb-3">
                        <h3 class="text-lg font-semibold text-gray-900">Page ${pageNumber} of ${totalPages}</h3>
                        <button id="toggle-image-btn" class="text-sm text-blue-600 hover:text-blue-700 font-medium">
                            <span class="toggle-text">Hide Image</span>
                        </button>
                    </div>
                    <div id="page-image-container" class="border border-gray-300 rounded-lg overflow-hidden bg-gray-50">
                        <img src="${pageImageUrl}" 
                            alt="Page ${pageNumber}" 
                            class="w-full h-auto"
                            onerror="this.parentElement.innerHTML='<div class=\\'p-8 text-center text-gray-500\\'>📄 Image not available</div>'">
                    </div>
                </div>
                
                <!-- Actions Bar -->
                <div class="flex items-center justify-between bg-white rounded-lg border border-gray-200 p-4">
                    <div class="flex items-center space-x-4">
                        <div class="flex items-center space-x-2 text-sm text-gray-500 bg-gray-50 px-3 py-2 rounded-full">
                            <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z"/>
                                <path fill-rule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"/>
                            </svg>
                            <span>${itemCount} extracted items</span>
                        </div>
                    </div>
                    <button id="add-item-btn" class="flex items-center space-x-2 px-4 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:shadow-lg transition-all">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd" />
                        </svg>
                        <span>Add Item</span>
                    </button>
                </div>
            </div>
        `;
    }

    // Data Table Rendering
    renderDataTable(items) {
        if (items.length === 0) {
            this.elements.dataTableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="px-6 py-12 text-center text-gray-500">
                        <div class="text-6xl mb-4">📊</div>
                        <p class="text-lg font-medium">No extracted data found on this page</p>
                        <p class="text-sm">Click "Add Item" to manually add financial data</p>
                    </td>
                </tr>
            `;
        } else {
            this.elements.dataTableBody.innerHTML = items.map((item, index) =>
                this.createDataRow(item, index)
            ).join('');
        }

        this.elements.loadingIndicator.classList.add('hidden');
    }

    createDataRow(item, index) {
        const isNew = item.id && item.id.toString().startsWith('new_');
        const rowClass = isNew ? 'bg-green-50 border-2 border-green-200' : '';

        // Determine the tag value and label for display
        let tagValue = '';
        let tagId = '';
        let tagLabel = '';

        // Priority: template field > confirmed tag
        if (item.template_field_id && item.template_field_label) {
            tagValue = item.template_field_label;
            tagId = item.template_field_id;
            tagLabel = item.template_field_label;
        } else if (item.confirmed_tag_id && item.confirmed_tag_label) {
            tagValue = item.confirmed_tag_label;
            tagId = item.confirmed_tag_id;
            tagLabel = item.confirmed_tag_label;
        }

        return `
            <tr class="form-row group hover:bg-gray-50 transition-colors ${rowClass}" data-item-id="${item.id}" ${isNew ? 'data-is-new="true"' : ''}>
                <td class="px-6 py-4 whitespace-nowrap">
                    <input type="number" 
                        class="w-20 px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        value="${item.financial_year || ''}" 
                        placeholder="YYYY"
                        min="1900"
                        max="2100"
                        data-field="financial_year">
                </td>
                <td class="px-6 py-4">
                    <input type="text" 
                        class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        value="${item.extracted_label || ''}" 
                        data-field="extracted_label">
                </td>
                <td class="px-6 py-4">
                    <input type="text" 
                        class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono bg-gray-50 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                        value="${item.extracted_value || ''}"
                        data-field="extracted_value">
                </td>
                <td class="px-6 py-4">
                    <div class="taxonomy-search-container relative">
                        <input type="text" 
                            class="taxonomy-search-input w-full px-4 py-3 border border-gray-300 rounded-lg bg-white text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all ${tagValue ? 'border-green-500 bg-green-50' : ''}"
                            placeholder="🔍 Search MBRS tags..."
                            value="${tagValue}"
                            data-field="confirmed_tag_id"
                            data-tag-id="${tagId}"
                            data-template-field-id="${item.template_field_id || ''}"
                            title="${item.template_xbrl_tag || ''}">
                        <div class="taxonomy-dropdown absolute top-full left-0 right-0 hidden bg-white border border-gray-300 rounded-b-lg shadow-lg z-50 max-h-60 overflow-y-auto"></div>
                        ${tagValue ? `<div class="text-xs text-green-600 mt-1">✓ ${item.template_xbrl_tag || 'Matched'}</div>` : ''}
                    </div>
                </td>
                <td class="px-6 py-4 text-center">
                    <label class="inline-flex items-center">
                        <input type="checkbox" 
                            class="w-5 h-5 text-blue-600 bg-gray-100 border-gray-300 rounded focus:ring-blue-500 focus:ring-2"
                            data-field="is_reviewed"
                            ${item.is_reviewed ? 'checked' : ''}>
                        <span class="ml-2 text-sm text-gray-600 reviewed-label">
                            ${item.is_reviewed ? '✅ Reviewed' : '⏳ Pending'}
                        </span>
                    </label>
                </td>
                <td class="px-6 py-4 text-center">
                    <button type="button" class="delete-btn p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors opacity-0 group-hover:opacity-100">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
                            <path fill-rule="evenodd" d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z"/>
                            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"/>
                        </svg>
                    </button>
                </td>
            </tr>
        `;
    }

    // Pagination Rendering
    renderPagination(currentPage, totalPages) {
        if (totalPages <= 1) {
            this.elements.paginationControls.classList.add('hidden');
            return;
        }

        this.elements.paginationControls.classList.remove('hidden');
        this.elements.itemsInfo.textContent = `Page ${currentPage} of ${totalPages}`;

        let paginationHTML = '';

        if (currentPage > 1) {
            paginationHTML += `
                <button data-page="1" class="pagination-btn px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors">First</button>
                <button data-page="${currentPage - 1}" class="pagination-btn px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors">Previous</button>
            `;
        }

        const startPage = Math.max(1, currentPage - 2);
        const endPage = Math.min(totalPages, currentPage + 2);

        for (let i = startPage; i <= endPage; i++) {
            if (i === currentPage) {
                paginationHTML += `<span class="px-3 py-2 text-sm bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg font-semibold">${i}</span>`;
            } else {
                paginationHTML += `<button data-page="${i}" class="pagination-btn px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors">${i}</button>`;
            }
        }

        if (currentPage < totalPages) {
            paginationHTML += `
                <button data-page="${currentPage + 1}" class="pagination-btn px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors">Next</button>
                <button data-page="${totalPages}" class="pagination-btn px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-lg transition-colors">Last</button>
            `;
        }

        this.elements.paginationNav.innerHTML = paginationHTML;
    }

    // UI State Management
    showWelcomeScreen() {
        this.elements.welcomeScreen.classList.remove('hidden');
        this.elements.jobContent.classList.add('hidden');
    }

    showJobContent() {
        this.elements.welcomeScreen.classList.add('hidden');
        this.elements.jobContent.classList.remove('hidden');
    }

    updateHeader(title) {
        this.elements.headerTitle.textContent = title;
    }

    showLoading(message = 'Loading data...') {
        this.elements.loadingIndicator.innerHTML = `
            <div class="text-center">
                <div class="loading-spinner mx-auto mb-4" style="width: 32px; height: 32px;"></div>
                <p class="text-gray-600">${message}</p>
            </div>
        `;
        this.elements.loadingIndicator.classList.remove('hidden');
    }

    hideLoading() {
        this.elements.loadingIndicator.classList.add('hidden');
    }

    updateReviewCount(reviewedCount, totalCount) {
        this.elements.reviewedCount.textContent = reviewedCount;
        this.elements.totalCount.textContent = totalCount;
    }

    showChangesIndicator() {
        if (this.elements.changesIndicator) {
            this.elements.changesIndicator.classList.remove('hidden');
        }
    }

    hideChangesIndicator() {
        if (this.elements.changesIndicator) {
            this.elements.changesIndicator.classList.add('hidden');
        }
    }

    updateDownloadButton(enabled, title = '') {
        // Keep button clickable; download flow itself handles validation and errors.
        this.elements.downloadBtn.disabled = false;
        if (title) {
            this.elements.downloadBtn.title = title;
        }
    }

    showSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (section) {
            section.classList.remove('hidden');
        }
    }

    hideSection(sectionId) {
        const section = document.getElementById(sectionId);
        if (section) {
            section.classList.add('hidden');
        }
    }
}