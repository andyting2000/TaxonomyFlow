// static/js/structured-review.js - NEW MODULE for structured review

export class StructuredReviewManager {
    constructor(api, dataManager) {
        this.api = api;
        this.dataManager = dataManager;
        this.statementTypes = [
            'Statement of Financial Position',
            'Statement of Comprehensive Income',
            'Statement of Changes in Equity',
            'Statement of Cash Flows',
            'Notes'
        ];
    }

    /**
     * Render data grouped by statement type (XBRL structure)
     */
    async renderStructuredView(jobId) {
        const container = document.getElementById('structured-review-container');
        
        if (!container) {
            console.error('Structured review container not found');
            return;
        }

        // Load all data
        const allData = await this.api.getExtractedData(jobId, 1, 1000);
        
        // Group by statement type
        const groupedData = this.groupByStatementType(allData.items);
        
        // Render each statement section
        let html = '<div class="space-y-6">';
        
        for (const statementType of this.statementTypes) {
            const items = groupedData[statementType] || [];
            
            if (items.length === 0) continue;
            
            html += this.renderStatementSection(statementType, items);
        }
        
        html += '</div>';
        
        container.innerHTML = html;
        
        // Initialize interactive features
        this.initializeSectionToggles();
        this.initializeReordering();
    }

    /**
     * Group items by statement type
     */
    groupByStatementType(items) {
        const grouped = {};
        
        for (const item of items) {
            const type = item.statement_type || 'Unclassified';
            
            if (!grouped[type]) {
                grouped[type] = [];
            }
            
            grouped[type].push(item);
        }
        
        // Sort items within each group by position/label
        for (const type in grouped) {
            grouped[type].sort((a, b) => {
                // Sort by financial year descending, then by label
                if (a.financial_year !== b.financial_year) {
                    return (b.financial_year || 0) - (a.financial_year || 0);
                }
                return (a.extracted_label || '').localeCompare(b.extracted_label || '');
            });
        }
        
        return grouped;
    }

    /**
     * Render a single statement section
     */
    renderStatementSection(statementType, items) {
        const sectionId = this.getSectionId(statementType);
        const itemCount = items.length;
        const reviewedCount = items.filter(i => i.is_reviewed).length;
        const completionRate = itemCount > 0 ? (reviewedCount / itemCount * 100).toFixed(0) : 0;
        
        return `
            <div class="statement-section bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden" data-statement="${statementType}">
                <!-- Section Header -->
                <div class="statement-header bg-gradient-to-r from-blue-50 to-indigo-50 p-4 cursor-pointer hover:from-blue-100 hover:to-indigo-100 transition-colors"
                     onclick="this.closest('.statement-section').querySelector('.statement-body').classList.toggle('hidden')">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center space-x-3">
                            <svg class="w-6 h-6 text-blue-600" fill="currentColor" viewBox="0 0 20 20">
                                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z"/>
                                <path fill-rule="evenodd" d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"/>
                            </svg>
                            <div>
                                <h3 class="text-lg font-semibold text-gray-900">${statementType}</h3>
                                <p class="text-sm text-gray-600">${itemCount} items · ${reviewedCount} reviewed</p>
                            </div>
                        </div>
                        
                        <div class="flex items-center space-x-4">
                            <!-- Progress Bar -->
                            <div class="w-32 bg-gray-200 rounded-full h-2">
                                <div class="bg-green-500 h-2 rounded-full transition-all" style="width: ${completionRate}%"></div>
                            </div>
                            <span class="text-sm font-medium text-gray-700">${completionRate}%</span>
                            
                            <!-- Chevron -->
                            <svg class="w-5 h-5 text-gray-400 transform transition-transform" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"/>
                            </svg>
                        </div>
                    </div>
                </div>
                
                <!-- Section Body -->
                <div class="statement-body p-6">
                    <table class="w-full">
                        <thead class="bg-gray-50 border-b border-gray-200">
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase w-16">Year</th>
                                <th class="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Label</th>
                                <th class="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">Value</th>
                                <th class="px-4 py-3 text-left text-xs font-semibold text-gray-700 uppercase">XBRL Tag</th>
                                <th class="px-4 py-3 text-center text-xs font-semibold text-gray-700 uppercase w-20">Status</th>
                                <th class="px-4 py-3 text-center text-xs font-semibold text-gray-700 uppercase w-16">Action</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-200">
                            ${items.map(item => this.renderItemRow(item)).join('')}
                        </tbody>
                    </table>
                </div>
            </div>
        `;
    }

    /**
     * Render a single item row
     */
    renderItemRow(item) {
        const statusIcon = item.is_reviewed 
            ? '<span class="text-green-600">✓</span>' 
            : '<span class="text-gray-400">○</span>';
        
        const tagClass = item.confirmed_tag_id 
            ? 'bg-green-50 border-green-200' 
            : 'bg-yellow-50 border-yellow-200';
        
        return `
            <tr class="hover:bg-gray-50 transition-colors" data-item-id="${item.id}">
                <td class="px-4 py-3 text-sm font-medium text-gray-900">${item.financial_year || '—'}</td>
                <td class="px-4 py-3 text-sm text-gray-900">${item.extracted_label}</td>
                <td class="px-4 py-3 text-sm font-mono text-gray-900">${item.extracted_value}</td>
                <td class="px-4 py-3">
                    <div class="taxonomy-search-container relative">
                        <input type="text" 
                            class="taxonomy-search-input w-full px-3 py-2 text-sm border ${tagClass} rounded-md"
                            value="${item.confirmed_tag_label || ''}"
                            placeholder="Search tags..."
                            data-field="confirmed_tag_id"
                            data-tag-id="${item.confirmed_tag_id || ''}">
                        <div class="taxonomy-dropdown absolute top-full left-0 right-0 hidden bg-white border rounded-b-md shadow-lg z-50 max-h-60 overflow-y-auto"></div>
                    </div>
                </td>
                <td class="px-4 py-3 text-center">
                    <label class="inline-flex items-center">
                        <input type="checkbox" 
                            class="w-4 h-4 text-blue-600 rounded"
                            data-field="is_reviewed"
                            ${item.is_reviewed ? 'checked' : ''}>
                        <span class="ml-2 text-sm">${statusIcon}</span>
                    </label>
                </td>
                <td class="px-4 py-3 text-center">
                    <button class="delete-btn p-1 text-red-600 hover:bg-red-50 rounded">
                        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
                            <path fill-rule="evenodd" d="M9 2a1 1 0 00-1 1v1H5a1 1 0 000 2h10a1 1 0 100-2h-3V3a1 1 0 00-1-1H9zM6 6v10a2 2 0 002 2h4a2 2 0 002-2V6H6z"/>
                        </svg>
                    </button>
                </td>
            </tr>
        `;
    }

    /**
     * Get sanitized section ID
     */
    getSectionId(statementType) {
        return statementType.toLowerCase().replace(/[^a-z0-9]/g, '-');
    }

    /**
     * Initialize section toggle functionality
     */
    initializeSectionToggles() {
        // Sections are toggleable via header click (handled in HTML)
    }

    /**
     * Initialize drag-and-drop reordering (future enhancement)
     */
    initializeReordering() {
        // TODO: Implement drag-and-drop for manual reordering
    }

    /**
     * Export structured data as XBRL preview
     */
    async generateXBRLPreview(jobId) {
        const allData = await this.api.getExtractedData(jobId, 1, 1000);
        const groupedData = this.groupByStatementType(allData.items);
        
        let preview = '<?xml version="1.0" encoding="UTF-8"?>\n';
        preview += '<xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">\n\n';
        
        for (const statementType of this.statementTypes) {
            const items = groupedData[statementType] || [];
            
            if (items.length === 0) continue;
            
            preview += `  <!-- ${statementType} -->\n`;
            
            for (const item of items) {
                if (!item.confirmed_tag_id) continue;
                
                const tag = item.confirmed_tag_label || 'UnknownTag';
                const value = item.extracted_value || '';
                const year = item.financial_year || '';
                
                preview += `  <${tag} contextRef="${year}">${value}</${tag}>\n`;
            }
            
            preview += '\n';
        }
        
        preview += '</xbrl>';
        
        return preview;
    }
}