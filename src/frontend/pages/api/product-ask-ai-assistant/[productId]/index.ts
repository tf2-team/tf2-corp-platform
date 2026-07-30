// Copyright The OpenTelemetry Authors
// SPDX-License-Identifier: Apache-2.0

import type { NextApiRequest, NextApiResponse } from 'next';
import InstrumentationMiddleware from '../../../../utils/telemetry/InstrumentationMiddleware';
import {AddItemRequest, Empty} from '../../../../protos/demo';
import ProductReviewService from '../../../../services/ProductReview.service';

type TResponse = string | Empty | {
    status: 'FALLBACK';
    answer: string;
    reason: string;
    claims: [];
};

const handler = async ({ method, body, query }: NextApiRequest, res: NextApiResponse<TResponse>) => {

    switch (method) {
        case 'POST': {
            const { productId = '' } = query;
            const { question, userId } = body ;

            try {
                const response = await ProductReviewService.askProductAIAssistant(
                    productId as string,
                    question as string,
                    userId as string,
                );

                return res.status(200).json(response);
            } catch {
                const reason = 'AI summary is temporarily unavailable. Please try again shortly.';
                return res.status(200).json({
                    status: 'FALLBACK',
                    answer: reason,
                    reason,
                    claims: [],
                });
            }
        }

        default: {
            return res.status(405).send('');
        }
    }
};

export default InstrumentationMiddleware(handler);
