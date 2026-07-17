// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import { ChannelCredentials } from '@grpc/grpc-js';
import {ProductReview, ProductReviewServiceClient} from '../../protos/demo';

const { PRODUCT_REVIEWS_ADDR = '' } = process.env;

const client = new ProductReviewServiceClient(PRODUCT_REVIEWS_ADDR, ChannelCredentials.createInsecure());

const ProductReviewGateway = () => ({

    getProductReviews(productId: string) {
        return new Promise<ProductReview []>((resolve, reject) =>
            client.getProductReviews({ productId }, (error, response) => (error ? reject(error) : resolve(response.productReviews)))
        );
    },
    getAverageProductReviewScore(productId: string) {
        return new Promise<string>((resolve, reject) =>
            client.getAverageProductReviewScore({ productId }, (error, response) => (error ? reject(error) : resolve(response.averageScore)))
        );
    },
    askProductAIAssistant(productId: string, question: string) {
        return new Promise<string>((resolve, reject) =>
            client.askProductAiAssistant({ productId, question }, (error, response) => {
                if (error) return reject(error);
                // response.response contains a JSON string with status, answer, reason, claims
                try {
                    const parsed = JSON.parse(response.response);
                    resolve(parsed as any);
                } catch {
                    // Backward compatibility: plain text response from older backends
                    resolve({ status: 'GROUNDED', answer: response.response, reason: '', claims: [] } as any);
                }
            })
        );
    },
});

export default ProductReviewGateway();
